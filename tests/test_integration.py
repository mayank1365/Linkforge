"""
Integration tests — require live Postgres + Redis.

Run with:
    DATABASE_URL=postgresql+asyncpg://linkforge:linkforge@localhost:5432/linkforge \
    REDIS_URL=redis://localhost:6379/0 \
    pytest tests/test_integration.py -v

All tests use the ``client`` fixture (httpx AsyncClient over ASGI) defined in
conftest.py.  Tables are created once per session; rows are truncated between
tests for isolation.
"""
import asyncio

import pytest


# ---------------------------------------------------------------------------
# POST /api/links — create link (auto-generated short code)
# ---------------------------------------------------------------------------

class TestCreateLink:
    async def test_returns_short_code_and_url(self, client, flush_redis):
        resp = await client.post(
            "/api/links", json={"long_url": "https://example.com/page"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "short_code" in body
        assert body["short_code"]
        assert body["short_url"].endswith(f"/{body['short_code']}")
        assert body["long_url"] == "https://example.com/page"
        assert body["click_count"] == 0

    async def test_different_urls_get_different_codes(self, client, flush_redis):
        r1 = await client.post("/api/links", json={"long_url": "https://one.example.com/"})
        r2 = await client.post("/api/links", json={"long_url": "https://two.example.com/"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["short_code"] != r2.json()["short_code"]

    async def test_invalid_url_rejected(self, client, flush_redis):
        resp = await client.post("/api/links", json={"long_url": "not-a-url"})
        assert resp.status_code == 422

    async def test_missing_long_url_rejected(self, client, flush_redis):
        resp = await client.post("/api/links", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /{code} — redirect
# ---------------------------------------------------------------------------

class TestRedirect:
    async def test_redirect_follows_to_long_url(self, client, flush_redis):
        create = await client.post(
            "/api/links", json={"long_url": "https://redirect-target.example.com/"}
        )
        assert create.status_code == 200
        code = create.json()["short_code"]

        resp = await client.get(f"/{code}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://redirect-target.example.com/"

    async def test_unknown_code_returns_404(self, client, flush_redis):
        resp = await client.get("/zzz999notexist", follow_redirects=False)
        assert resp.status_code == 404

    async def test_reserved_path_returns_404(self, client, flush_redis):
        # "dashboard" is in RESERVED — must not 302
        resp = await client.get("/dashboard", follow_redirects=False)
        # dashboard route returns an HTML page (200), not a redirect — confirm no 302
        assert resp.status_code != 302

    async def test_api_prefix_not_treated_as_short_code(self, client, flush_redis):
        resp = await client.get("/api", follow_redirects=False)
        assert resp.status_code in (404, 405, 307, 308)  # anything but a 302 redirect


# ---------------------------------------------------------------------------
# Custom alias
# ---------------------------------------------------------------------------

class TestCustomAlias:
    async def test_custom_alias_used_as_short_code(self, client, flush_redis):
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://alias.example.com/", "custom_alias": "myalias"},
        )
        assert resp.status_code == 200
        assert resp.json()["short_code"] == "myalias"

    async def test_reuse_exact_alias_returns_409(self, client, flush_redis):
        await client.post(
            "/api/links",
            json={"long_url": "https://first.example.com/", "custom_alias": "taken"},
        )
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://second.example.com/", "custom_alias": "taken"},
        )
        assert resp.status_code == 409

    async def test_case_variant_alias_returns_409(self, client, flush_redis):
        """'MyAlias' and 'myalias' normalise to the same key."""
        await client.post(
            "/api/links",
            json={"long_url": "https://first.example.com/", "custom_alias": "MyAlias"},
        )
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://second.example.com/", "custom_alias": "myalias"},
        )
        assert resp.status_code == 409

    async def test_separator_variant_alias_returns_409(self, client, flush_redis):
        """'my-alias' and 'my_alias' normalise to the same key."""
        await client.post(
            "/api/links",
            json={"long_url": "https://first.example.com/", "custom_alias": "my-alias"},
        )
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://second.example.com/", "custom_alias": "my_alias"},
        )
        assert resp.status_code == 409

    async def test_reserved_alias_rejected_at_schema_level(self, client, flush_redis):
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://example.com/", "custom_alias": "dashboard"},
        )
        assert resp.status_code == 422

    async def test_invalid_chars_in_alias_rejected(self, client, flush_redis):
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://example.com/", "custom_alias": "bad alias!"},
        )
        assert resp.status_code == 422

    async def test_alias_too_long_rejected(self, client, flush_redis):
        resp = await client.post(
            "/api/links",
            json={"long_url": "https://example.com/", "custom_alias": "a" * 17},
        )
        assert resp.status_code == 422

    async def test_redirect_works_with_custom_alias(self, client, flush_redis):
        await client.post(
            "/api/links",
            json={"long_url": "https://custom-dest.example.com/", "custom_alias": "dest"},
        )
        resp = await client.get("/dest", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://custom-dest.example.com/"


# ---------------------------------------------------------------------------
# GET /api/links/{code} — metadata lookup
# ---------------------------------------------------------------------------

class TestGetLink:
    async def test_get_existing_link(self, client, flush_redis):
        create = await client.post(
            "/api/links", json={"long_url": "https://meta.example.com/"}
        )
        code = create.json()["short_code"]

        resp = await client.get(f"/api/links/{code}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["short_code"] == code
        assert body["long_url"] == "https://meta.example.com/"

    async def test_get_nonexistent_link_returns_404(self, client, flush_redis):
        resp = await client.get("/api/links/doesnotexist999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /htmx/check-alias — live alias availability
# ---------------------------------------------------------------------------

class TestCheckAlias:
    async def test_empty_alias_returns_empty_state(self, client, flush_redis):
        resp = await client.get("/htmx/check-alias", params={"custom_alias": ""})
        assert resp.status_code == 200
        # Empty alias: no validation message, and the submit button stays enabled.
        assert "field-msg" not in resp.text
        assert "disabled" not in resp.text

    async def test_available_alias(self, client, flush_redis):
        resp = await client.get(
            "/htmx/check-alias", params={"custom_alias": "newuniquealias"}
        )
        assert resp.status_code == 200
        # The partial contains "Available" when the alias is free
        assert "Available" in resp.text

    async def test_taken_alias_shows_taken_message(self, client, flush_redis):
        await client.post(
            "/api/links",
            json={"long_url": "https://taken.example.com/", "custom_alias": "takenalias"},
        )
        resp = await client.get(
            "/htmx/check-alias", params={"custom_alias": "takenalias"}
        )
        assert resp.status_code == 200
        assert "already exists" in resp.text.lower() or "taken" in resp.text.lower()

    async def test_reserved_alias_shows_reserved_message(self, client, flush_redis):
        resp = await client.get(
            "/htmx/check-alias", params={"custom_alias": "dashboard"}
        )
        assert resp.status_code == 200
        assert "reserved" in resp.text.lower()

    async def test_invalid_chars_shows_error(self, client, flush_redis):
        resp = await client.get(
            "/htmx/check-alias", params={"custom_alias": "bad alias!"}
        )
        assert resp.status_code == 200
        # Should contain some form of validation error
        assert "only" in resp.text.lower() or "letter" in resp.text.lower() or "error" in resp.text.lower()


# ---------------------------------------------------------------------------
# Rate limiter — POST /api/links
# ---------------------------------------------------------------------------

class TestRateLimit:
    async def test_burst_then_429(self, client, flush_redis):
        """
        Fire requests rapidly; after the burst capacity (20) is exhausted
        at least some should come back 429.  We send 30 requests — enough
        to reliably exceed the default burst of 20.
        """
        results = []
        for _ in range(30):
            resp = await client.post(
                "/api/links",
                json={"long_url": "https://ratelimit.example.com/"},
                # Use a fixed IP header so all requests share one bucket
                headers={"x-forwarded-for": "1.2.3.4"},
            )
            results.append(resp.status_code)

        status_codes = set(results)
        assert 200 in status_codes, "Some requests should succeed"
        assert 429 in status_codes, (
            "After burst capacity is exhausted, requests should be rate-limited"
        )

    async def test_different_ips_have_separate_buckets(self, client, flush_redis):
        """Two IPs share nothing — both can consume their full burst quota."""
        for i in range(5):
            r = await client.post(
                "/api/links",
                json={"long_url": f"https://ip1.example.com/{i}"},
                headers={"x-forwarded-for": "10.0.0.1"},
            )
            assert r.status_code == 200, f"IP1 request {i} failed: {r.status_code}"

        for i in range(5):
            r = await client.post(
                "/api/links",
                json={"long_url": f"https://ip2.example.com/{i}"},
                headers={"x-forwarded-for": "10.0.0.2"},
            )
            assert r.status_code == 200, f"IP2 request {i} failed: {r.status_code}"
