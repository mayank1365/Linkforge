"""Distributed token-bucket rate limiting, backed by a Redis Lua script."""
from pathlib import Path

from fastapi import HTTPException, Request, status

from .config import settings
from .redis_client import redis_client

_LUA_PATH = Path(__file__).resolve().parent / "lua" / "token_bucket.lua"
_LUA_SCRIPT = _LUA_PATH.read_text()

# register_script returns an AsyncScript; Redis caches the script by SHA after
# the first EVAL, so subsequent calls use the fast EVALSHA path.
_token_bucket = redis_client.register_script(_LUA_SCRIPT)


async def check_rate_limit(
    key: str,
    capacity: int | None = None,
    refill: float | None = None,
    cost: int = 1,
) -> tuple[bool, float]:
    """Return (allowed, remaining_tokens) for the given bucket key."""
    capacity = capacity or settings.rate_limit_capacity
    refill = refill or settings.rate_limit_refill
    allowed, remaining = await _token_bucket(
        keys=[f"rl:{key}"], args=[capacity, refill, cost]
    )
    return bool(int(allowed)), float(remaining)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency: 429 when the caller's bucket is empty."""
    ip = client_ip(request)
    allowed, remaining = await check_rate_limit(f"api:{ip}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Slow down.",
            headers={"Retry-After": "1"},
        )
