"""Seed demo links and synthetic click history so the dashboard looks alive.

Usage (with the stack running):
    python scripts/seed.py
"""
import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics import QUEUE_KEY  # noqa: E402
from app.base62 import encode  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal, Base, engine  # noqa: E402
from app.redis_client import redis_client  # noqa: E402
from sqlalchemy import text  # noqa: E402

DEMO = [
    "https://fastapi.tiangolo.com/",
    "https://redis.io/docs/latest/develop/interact/programmability/eval-intro/",
    "https://htmx.org/docs/",
    "https://www.postgresql.org/docs/current/",
    "https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html",
    "https://github.com/",
    "https://news.ycombinator.com/",
    "https://realpython.com/",
]
DEVICES = ["desktop", "mobile", "mobile", "tablet", "bot"]
COUNTRIES = ["US", "IN", "GB", "DE", "BR", "JP"]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    codes = []
    async with SessionLocal() as session:
        for url in DEMO:
            new_id = (
                await session.execute(
                    text("INSERT INTO links (long_url) VALUES (:u) RETURNING id"),
                    {"u": url},
                )
            ).scalar_one()
            code = encode(new_id + settings.short_code_offset)
            await session.execute(
                text("UPDATE links SET short_code = :c WHERE id = :id"),
                {"c": code, "id": new_id},
            )
            codes.append((new_id, code))
        await session.commit()

    # Generate ~3000 synthetic clicks spread over the last 24h and enqueue them
    # so the real ingestion worker processes them into the rollup tables.
    now = datetime.now(timezone.utc)
    total = 0
    pipe = redis_client.pipeline()
    for _ in range(3000):
        link_id, _code = random.choice(codes)
        # bias popularity toward the first few links
        if random.random() < 0.6:
            link_id, _code = codes[random.randint(0, 2)]
        ts = now - timedelta(
            hours=random.randint(0, 23), minutes=random.randint(0, 59)
        )
        event = {
            "link_id": link_id,
            "ts": ts.isoformat(),
            "referrer": random.choice([None, "https://t.co", "https://google.com"]),
            "device": random.choice(DEVICES),
            "country": random.choice(COUNTRIES),
        }
        pipe.lpush(QUEUE_KEY, json.dumps(event))
        total += 1
    await pipe.execute()

    print(f"Seeded {len(codes)} links and enqueued {total} clicks.")
    print("Sample short URLs:")
    for _id, code in codes[:5]:
        print(f"  {settings.base_url}/{code}")
    print("The ingestion worker will drain the queue into the dashboard shortly.")
    await redis_client.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
