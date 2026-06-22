"""Load test for LinkForge.

Seeds a pool of links on start, then hammers the redirect hot path (the read
path that matters for throughput), with a smaller fraction of writes.

Run:
    locust -f locustfile.py --host http://localhost:8000
or headless:
    locust -f locustfile.py --host http://localhost:8000 \
        --users 200 --spawn-rate 50 --run-time 60s --headless
"""
import random

from locust import HttpUser, between, events, task

SHORT_CODES: list[str] = []


@events.test_start.add_listener
def _seed(environment, **_):
    """Create a pool of links to redirect against."""
    import httpx

    host = environment.host or "http://localhost:8000"
    with httpx.Client(base_url=host, timeout=10) as client:
        for i in range(50):
            r = client.post(
                "/api/links",
                json={"long_url": f"https://example.com/load-test/{i}"},
            )
            if r.status_code == 200:
                SHORT_CODES.append(r.json()["short_code"])
    print(f"[locust] seeded {len(SHORT_CODES)} links")


class RedirectUser(HttpUser):
    wait_time = between(0, 0.01)

    @task(20)
    def follow_redirect(self):
        if not SHORT_CODES:
            return
        code = random.choice(SHORT_CODES)
        # don't follow the 302 — we measure the redirect endpoint itself
        self.client.get(
            f"/{code}", allow_redirects=False, name="/[code] (redirect)"
        )

    @task(1)
    def create_link(self):
        self.client.post(
            "/api/links",
            json={"long_url": f"https://example.com/new/{random.random()}"},
            name="/api/links (create)",
        )
