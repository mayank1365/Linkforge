"""
Shared pytest fixtures for the LinkForge test suite.

Integration tests require a live Postgres + Redis (see CI env vars or
DATABASE_URL / REDIS_URL in the environment).  Pure unit tests (base62,
normalize_alias, parse_device) have no external dependencies.
"""
import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Ensure the app's Settings picks up env overrides *before* the app module is
# imported so that the engine is built with the right DATABASE_URL.
# ---------------------------------------------------------------------------
from app.database import Base
from app.main import app

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://linkforge:linkforge@localhost:5432/linkforge",
)

_test_engine = create_async_engine(_TEST_DB_URL, echo=False)
_TestSession = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=False)
async def create_tables():
    """Create all tables once per test session (idempotent)."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Leave tables in place so failures are inspectable; CI starts fresh anyway.


@pytest_asyncio.fixture
async def truncate_tables(create_tables):
    """Truncate mutable tables before each integration test for isolation."""
    async with _test_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE links, click_events, click_stats_hourly "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


# ---------------------------------------------------------------------------
# HTTP client (no lifespan — we manage the DB ourselves)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(truncate_tables):
    """
    AsyncClient wired to the ASGI app.

    ASGITransport does NOT run the FastAPI lifespan, so tables are created
    by the ``create_tables`` fixture above and the ingestion worker is not
    running (fine — redirect only enqueues to Redis, not the worker).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Redis flush between tests (so rate-limit buckets don't bleed across tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=False)
async def flush_redis():
    """Flush the Redis test DB before the test that requests this fixture."""
    from app.redis_client import redis_client
    await redis_client.flushdb()
    yield
    # Optionally flush after too — keep it simple, flush before is enough.
