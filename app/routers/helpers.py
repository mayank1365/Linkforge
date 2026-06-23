"""Shared logic used by both the JSON API and the HTMX endpoints."""
from fastapi import HTTPException
from sqlalchemy import text

from ..base62 import encode
from ..config import settings

ALIAS_TAKEN_MSG = "This alias already exists. Please choose a different alias."


def normalize_alias(alias: str) -> str:
    """Canonical form for uniqueness: case-insensitive, '-' and '_' equivalent.

    So Test, TEST, test all collide, and test-alias / test_alias collide.
    """
    return alias.strip().lower().replace("_", "-")


async def alias_is_taken(session, alias: str) -> bool:
    """True if any existing code matches the alias under normalized comparison."""
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM links "
                "WHERE lower(replace(short_code, '_', '-')) = :norm LIMIT 1"
            ),
            {"norm": normalize_alias(alias)},
        )
    ).first()
    return row is not None


async def create_link_record(session, long_url: str, custom_alias: str | None):
    """Insert a link and return its full row.

    With a custom alias we insert directly. Otherwise we insert first to obtain
    the auto-increment id, then derive a base62 short code from it — the classic
    collision-free shortener trick.
    """
    if custom_alias:
        if await alias_is_taken(session, custom_alias):
            raise HTTPException(409, ALIAS_TAKEN_MSG)
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
