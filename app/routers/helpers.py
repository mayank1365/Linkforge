"""Shared logic used by both the JSON API and the HTMX endpoints."""
from fastapi import HTTPException
from sqlalchemy import text

from ..base62 import encode
from ..config import settings


async def create_link_record(session, long_url: str, custom_alias: str | None):
    """Insert a link and return its full row.

    With a custom alias we insert directly. Otherwise we insert first to obtain
    the auto-increment id, then derive a base62 short code from it — the classic
    collision-free shortener trick.
    """
    if custom_alias:
        exists = (
            await session.execute(
                text("SELECT 1 FROM links WHERE short_code = :c"),
                {"c": custom_alias},
            )
        ).first()
        if exists:
            raise HTTPException(409, "alias already taken")
        row = (
            await session.execute(
                text(
                    "INSERT INTO links (short_code, long_url) VALUES (:c, :u) "
                    "RETURNING id, short_code, long_url, click_count, created_at"
                ),
                {"c": custom_alias, "u": long_url},
            )
        ).first()
    else:
        new_id = (
            await session.execute(
                text("INSERT INTO links (long_url) VALUES (:u) RETURNING id"),
                {"u": long_url},
            )
        ).scalar_one()
        code = encode(new_id + settings.short_code_offset)
        row = (
            await session.execute(
                text(
                    "UPDATE links SET short_code = :c WHERE id = :id "
                    "RETURNING id, short_code, long_url, click_count, created_at"
                ),
                {"c": code, "id": new_id},
            )
        ).first()
    await session.commit()
    return row
