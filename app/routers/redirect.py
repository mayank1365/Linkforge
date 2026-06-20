"""The redirect hot path — optimised for throughput.

  1. cache-aside lookup in Redis (sub-ms on a hit)
  2. fall back to Postgres on a miss, then warm the cache
  3. O(1) enqueue of the click event (no synchronous analytics writes)
  4. 302 to the destination
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from ..analytics import CACHE_HIT_KEY, CACHE_MISS_KEY, enqueue_click
from ..config import settings
from ..database import SessionLocal
from ..redis_client import redis_client

router = APIRouter()

# Paths that must never be treated as short codes.
RESERVED = {"api", "dashboard", "static", "healthz", "htmx", "favicon.ico", ""}


def parse_device(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if any(b in ua for b in ("bot", "spider", "crawl")):
        return "bot"
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if any(m in ua for m in ("mobi", "android", "iphone")):
        return "mobile"
    return "desktop"


@router.get("/{short_code}")
async def redirect(short_code: str, request: Request):
    if short_code in RESERVED:
        return HTMLResponse("<h1>404 — not found</h1>", status_code=404)

    cache_key = f"link:{short_code}"
    cached = await redis_client.get(cache_key)

    if cached:
        await redis_client.incr(CACHE_HIT_KEY)
        link_id_str, long_url = cached.split("|", 1)
        link_id = int(link_id_str)
    else:
        await redis_client.incr(CACHE_MISS_KEY)
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id, long_url FROM links "
                        "WHERE short_code = :c AND is_active = true"
                    ),
                    {"c": short_code},
                )
            ).first()
        if not row:
            return HTMLResponse(
                "<h1>404 — link not found</h1>", status_code=404
            )
        link_id, long_url = row.id, row.long_url
        await redis_client.set(
            cache_key, f"{link_id}|{long_url}", ex=settings.cache_ttl_seconds
        )

    await enqueue_click(
        link_id,
        request.headers.get("referer"),
        parse_device(request.headers.get("user-agent")),
        request.headers.get("cf-ipcountry") or request.headers.get("x-country"),
    )
    return RedirectResponse(long_url, status_code=302)
