"""Async click ingestion + analytics rollups.

Hot path (redirect) only does an O(1) Redis LPUSH, so it stays fast under load.
A background worker drains the queue in batches and writes:
  * raw rows into click_events
  * pre-aggregated hourly counts into click_stats_hourly (upsert)
  * a denormalised click_count on links
"""
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text

from .config import settings
from .database import SessionLocal
from .redis_client import redis_client

QUEUE_KEY = "clicks:queue"
CACHE_HIT_KEY = "stats:cache_hits"
CACHE_MISS_KEY = "stats:cache_misses"


async def enqueue_click(
    link_id: int,
    referrer: str | None,
    device: str | None,
    country: str | None,
) -> None:
    """O(1) push onto the Redis ingestion queue (fire-and-forget)."""
    event = {
        "link_id": link_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "referrer": referrer,
        "device": device,
        "country": country,
    }
    await redis_client.lpush(QUEUE_KEY, json.dumps(event))


async def _drain_once() -> int:
    """Pop one batch off the queue and persist it. Returns rows processed."""
    raw = await redis_client.rpop(QUEUE_KEY, settings.ingest_batch_size)
    if not raw:
        return 0

    events = []
    for item in raw:
        ev = json.loads(item)
        ev["ts"] = datetime.fromisoformat(ev["ts"])
        events.append(ev)

    hourly: Counter = Counter()
    per_link: Counter = Counter()
    for ev in events:
        bucket = ev["ts"].replace(minute=0, second=0, microsecond=0)
        hourly[(ev["link_id"], bucket)] += 1
        per_link[ev["link_id"]] += 1

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO click_events (link_id, ts, referrer, device, country)
                VALUES (:link_id, :ts, :referrer, :device, :country)
                """
            ),
            events,
        )
        await session.execute(
            text(
                """
                INSERT INTO click_stats_hourly (link_id, bucket, clicks)
                VALUES (:link_id, :bucket, :clicks)
                ON CONFLICT (link_id, bucket)
                DO UPDATE SET clicks = click_stats_hourly.clicks + EXCLUDED.clicks
                """
            ),
            [
                {"link_id": lid, "bucket": bkt, "clicks": n}
                for (lid, bkt), n in hourly.items()
            ],
        )
        await session.execute(
            text("UPDATE links SET click_count = click_count + :inc WHERE id = :id"),
            [{"id": lid, "inc": n} for lid, n in per_link.items()],
        )
        await session.commit()

    return len(events)


async def ingestion_worker(stop_event: asyncio.Event) -> None:
    """Long-running background task; keeps draining until asked to stop."""
    while not stop_event.is_set():
        try:
            processed = await _drain_once()
            if processed == 0:
                await asyncio.sleep(settings.ingest_interval)
        except Exception as exc:  # pragma: no cover - keep the worker alive
            print(f"[ingestion_worker] error: {exc!r}")
            await asyncio.sleep(1)
    # final flush on shutdown
    try:
        while await _drain_once():
            pass
    except Exception as exc:  # pragma: no cover
        print(f"[ingestion_worker] final flush error: {exc!r}")


# --------------------------------------------------------------------------- #
# Dashboard queries (read against the pre-aggregated rollup tables)
# --------------------------------------------------------------------------- #
async def get_overview(session) -> dict:
    total_links = (
        await session.execute(text("SELECT COUNT(*) FROM links"))
    ).scalar_one()
    total_clicks = (
        await session.execute(
            text("SELECT COALESCE(SUM(click_count), 0) FROM links")
        )
    ).scalar_one()
    hits = int(await redis_client.get(CACHE_HIT_KEY) or 0)
    misses = int(await redis_client.get(CACHE_MISS_KEY) or 0)
    total_lookups = hits + misses
    hit_rate = (hits / total_lookups * 100) if total_lookups else 0.0
    queue_depth = await redis_client.llen(QUEUE_KEY)
    return {
        "total_links": total_links,
        "total_clicks": total_clicks,
        "cache_hits": hits,
        "cache_misses": misses,
        "hit_rate": round(hit_rate, 1),
        "queue_depth": queue_depth,
    }


async def get_hourly_series(session, hours: int = 24) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT date_trunc('hour', bucket) AS hr, SUM(clicks) AS clicks
                FROM click_stats_hourly
                WHERE bucket >= now() - (:hours * interval '1 hour')
                GROUP BY hr
                ORDER BY hr
                """
            ),
            {"hours": hours},
        )
    ).all()
    return [{"hour": r.hr, "clicks": int(r.clicks)} for r in rows]


async def get_top_links(session, limit: int = 10) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT short_code, long_url, click_count
                FROM links
                WHERE short_code IS NOT NULL
                ORDER BY click_count DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).all()
    return [
        {
            "short_code": r.short_code,
            "long_url": r.long_url,
            "click_count": int(r.click_count),
        }
        for r in rows
    ]


async def get_device_breakdown(session) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT COALESCE(device, 'unknown') AS device, COUNT(*) AS n
                FROM click_events
                GROUP BY device
                ORDER BY n DESC
                """
            )
        )
    ).all()
    return [{"device": r.device, "count": int(r.n)} for r in rows]
