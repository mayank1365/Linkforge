"""Multi-endpoint stress scenario for LinkForge.

Seeds a pool of links, then drives a realistic, read-heavy mix:
  - redirect hot path
  - live alias availability check (does a normalized uniqueness scan)
  - link creation (write path)
  - dashboard analytics read

Run headless, e.g.:
    python -m locust -f stress_test.py --host http://localhost:8000 \
        --users 150 --spawn-rate 50 --run-time 45s --headless

For capacity runs, temporarily raise the rate limit (it only guards the write
endpoints) so it doesn't mask raw throughput — e.g. a docker-compose.override.yml
setting RATE_LIMIT_CAPACITY / RATE_LIMIT_REFILL high. See report.md.
"""
import random
import string

from locust import HttpUser, between, events, task

SHORT_CODES: list[str] = []


@events.test_start.add_listener
def _seed(environment, **_):
    import httpx

    host = environment.host or "http://localhost:8000"
    with httpx.Client(base_url=host, timeout=15) as client:
        for i in range(100):
            r = client.post("/api/links", json={"long_url": f"https://example.com/seed/{i}"})
            if r.status_code == 200:
                SHORT_CODES.append(r.json()["short_code"])
    print(f"[stress] seeded {len(SHORT_CODES)} links")


def rand_alias() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


class MixedUser(HttpUser):
    wait_time = between(0, 0.005)  # ~zero think time: push as hard as possible

    @task(15)
    def redirect(self):
        if not SHORT_CODES:
            return
        code = random.choice(SHORT_CODES)
        self.client.get(f"/{code}", allow_redirects=False, name="GET /[code] redirect")

    @task(5)
    def alias_check(self):
        self.client.get(
            "/htmx/check-alias",
            params={"custom_alias": rand_alias()},
            name="GET /htmx/check-alias",
        )

    @task(2)
    def create(self):
        self.client.post(
            "/api/links",
            json={"long_url": f"https://example.com/new/{random.random()}"},
            name="POST /api/links create",
        )

    @task(1)
    def dashboard(self):
        self.client.get("/htmx/stats", name="GET /htmx/stats dashboard")
