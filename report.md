# LinkForge — Stress Test Report

**Date:** 2026-06-23
**Build:** `main` @ `9ca30d1` (live alias validation)
**Verdict:** ✅ Zero failures across ~147,000 requests. The cached redirect path
stays fast under 4–6× overload and recovers instantly after a spike. Throughput is
capped by the single application worker (one CPU core); the DB-bound endpoints are
the first to slow down under saturation.

---

## 1. Test environment

| | |
|---|---|
| Host | Apple Silicon laptop, Docker Desktop |
| App | FastAPI under **a single Uvicorn worker** (same shape as the Render free tier) |
| Datastores | Postgres 16-alpine, Redis 7-alpine (containers) |
| Load generator | Locust 2.32, **running on the same machine** as the stack |
| Driver | `asyncpg` + SQLAlchemy async + `redis.asyncio` |

> **Important caveat:** the app, Postgres, Redis, *and* the load generator all share
> one machine, so CPU contention makes these numbers a **conservative floor** — real
> throughput on dedicated hardware (and with multiple workers) is higher. For the
> capacity runs the rate limiter was raised so it wouldn't mask raw throughput; the
> limiter was tested separately (§5) with default settings.

Workload mix (per the multi-endpoint scenario): **redirect 15 / alias-check 5 /
create 2 / dashboard 1**, against a seeded pool of 100 links.

---

## 2. Headline numbers

| Scenario | Users | Total reqs | Throughput | Failures | Redirect p50 / p95 / p99 |
|---|--:|--:|--:|--:|--|
| Steady state | 150 | 53,944 | **1,204 req/s** | **0.00%** | 39 / 71 / 98 ms |
| High load | 400 | 52,757 | **1,179 req/s** | **0.00%** | 41 / 93 / 140 ms |
| Spike (ramp 300/s) | 600 | 40,679 | **1,363 req/s** | **0.00%** | 38 / 120 / 640 ms |

- **0 failed requests** in every scenario.
- **Cache hit rate: 99.53%** (96,270 hits / 453 misses) — the cache-aside layer kept
  virtually all redirect traffic off Postgres.
- **Ingestion queue drained to 0** after every run — the background worker kept up
  with the click firehose; no analytics backlog.

---

## 3. Per-endpoint latency

### Steady state — 150 users
| Endpoint | req/s | p50 | p95 | p99 | max | fails |
|---|--:|--:|--:|--:|--:|--:|
| `GET /[code]` redirect | 789 | 39 | 71 | 98 | 708 | 0 |
| `GET /htmx/check-alias` | 258 | 220 | 570 | 820 | 1729 | 0 |
| `POST /api/links` create | 106 | 250 | 610 | 880 | 1505 | 0 |
| `GET /htmx/stats` dashboard | 51 | 290 | 640 | 900 | 1615 | 0 |

### High load — 400 users
| Endpoint | req/s | p50 | p95 | p99 | max | fails |
|---|--:|--:|--:|--:|--:|--:|
| `GET /[code]` redirect | 770 | 41 | 93 | 140 | 765 | 0 |
| `GET /htmx/check-alias` | 256 | 800 | 2300 | 3200 | 6211 | 0 |
| `POST /api/links` create | 102 | 830 | 2300 | 3100 | 6509 | 0 |
| `GET /htmx/stats` dashboard | 52 | 890 | 2400 | 3300 | 5208 | 0 |

The redirect path degrades only mildly (p99 98 → 140 ms) as concurrency rises 2.7×,
because it is served from Redis. The DB-bound endpoints (alias-check, create,
dashboard) absorb the queueing once the single worker and Postgres saturate.

---

## 4. Resource utilisation (mid-test @ 400 users)

| Container | CPU | Memory |
|---|--:|--:|
| `linkforge-app` | **100.6%** (1 core, pinned) | 86 MiB |
| `linkforge-db` (Postgres) | 139.8% | 115 MiB |
| `linkforge-redis` | 7.2% | 13 MiB |

**Bottleneck:** the application worker is pinned at one full core, and Postgres is the
next constraint. Redis is nearly idle — caching and the rate limiter are cheap.

---

## 5. Rate limiter (default config: 20 burst, 5 tokens/s, per IP)

Fired 50 rapid `POST /api/links` from one IP:

```
200 OK  : 23      (20 burst + ~3 refilled during the burst)
429     : 27
```

After a 3-second pause, the next 5 requests all returned **200** — tokens refilled
exactly as designed. The distributed token bucket throttles correctly and recovers.

---

## 6. Resilience & recovery

- **Spike:** ramping to 600 users at 300/s produced 0 failures; redirect p95 held at
  120 ms (p99 640 ms during the burst).
- **Recovery:** immediately after the spike, redirect latency returned to **3–8 ms** —
  no lingering degradation, no connection-pool exhaustion, no errors.
- **Graceful degradation:** under overload the system slows (latency rises) but never
  drops requests or returns 5xx.

---

## 7. Key findings

1. ✅ **Cache-aside is doing its job** — 99.5% hit rate; redirects stay sub-150 ms p95
   even at 4× the saturation point.
2. ✅ **Async ingestion keeps up** — the click queue never backed up; rollups stayed
   current.
3. ✅ **No failures, clean recovery** — the architecture degrades gracefully and
   self-heals after spikes.
4. ⚠️ **`/htmx/check-alias` is the heaviest endpoint.** It runs a normalized
   uniqueness query — `lower(replace(short_code,'_','-')) = :norm` — which **can't use
   the plain `short_code` index** and does a sequential scan. Under load it dominates
   DB time (p99 3.2 s @ 400 users).
5. ⚠️ **Throughput ceiling ≈ 1,200 req/s** here, set by the single worker on one core.

---

## 8. Recommendations

| Priority | Improvement | Why |
|---|---|---|
| **High** | Add a **functional index**: `CREATE INDEX ix_links_alias_norm ON links (lower(replace(short_code,'_','-')));` (or store a normalized `alias_key` column with a unique index) | Turns the alias-check scan into an index lookup — removes the main DB hotspot and lets the DB enforce normalized uniqueness atomically (closes the create-time race). |
| **High** | Run **multiple workers / horizontally scale** the app (e.g. `--workers N`, or more Render instances behind the LB) | App is CPU-bound on one core; it's stateless, so it scales linearly. |
| Medium | **Debounce/guard** the live alias check (already 350 ms debounced; consider min-length ≥ 2 and a short client cache) | Cuts redundant DB hits while typing. |
| Medium | **Postgres read replica** for dashboard/analytics reads | Keeps heavy aggregate reads off the primary. |
| Low | **Cache negative lookups** / add a short TTL cache for alias availability | Repeated checks for the same alias skip the DB. |
| Low | Tune the **asyncpg pool size** for higher worker counts | Avoid pool contention at scale. |

---

## 9. Notes on the live Render deployment

The live site (`https://linkforge-9gwq.onrender.com`) runs on Render's **free tier**:
~0.1 CPU, 512 MB, single instance that **sleeps after ~15 min idle** (first request
cold-starts in ~30–50 s). It is sized for demos, not load — these stress numbers were
measured locally where the worker gets a full core. The *architecture* is what scales;
the free tier is the constraint.

---

## 10. How to reproduce

```bash
# 1. bring up the stack
docker compose up -d --build

# 2. (capacity runs) temporarily raise the rate limit so it doesn't mask throughput
#    via a docker-compose.override.yml setting RATE_LIMIT_CAPACITY / REFILL high

# 3. run the multi-endpoint scenario (stress_test.py)
python -m locust -f stress_test.py --host http://localhost:8000 \
  --users 400 --spawn-rate 80 --run-time 45s --headless

# committed single-purpose load test (redirect-focused):
python -m locust -f locustfile.py --host http://localhost:8000 \
  --users 200 --spawn-rate 50 --run-time 60s --headless
```
