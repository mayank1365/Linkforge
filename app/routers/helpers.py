"""Shared logic used by both the JSON API and the HTMX endpoints."""
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..base62 import encode
from ..config import settings

ALIAS_TAKEN_MSG = "This alias already exists. Please choose a different alias."


def normalize_alias(alias: str) -> str:
    """Canonical form for uniqueness: case-insensitive, '-' and '_' equivalent.

    So Test, TEST, test all collide, and test-alias / test_alias collide.
    """
    return alias.strip().lower().replace("_", "-")


async def alias_is_taken(session, alias: str) -> bool:
    """True if any existing alias_key matches the normalised alias.

    Queries the indexed alias_key column directly instead of applying a
    functional expression on short_code, giving a plain index seek.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM links "
                "WHERE alias_key = :norm LIMIT 1"
            ),
            {"norm": normalize_alias(alias)},
        )
    ).first()
    return row is not None


async def create_link_record(session, long_url: str, custom_alias: str | None):
    """Insert a link and return its full row.

    With a custom alias we insert directly (also setting alias_key to the
    normalised form so the DB-level unique constraint can enforce
    case/separator-insensitive uniqueness). Otherwise we insert first to obtain
    the auto-increment id, then derive a base62 short code from it — the
    classic collision-free shortener trick.

    An IntegrityError on insert (concurrent race on alias_key) is caught and
    re-raised as the same 409 the pre-check would have produced, so callers
    always get the friendly message regardless of timing.
    """
    if custom_alias:
        if await alias_is_taken(session, custom_alias):
            raise HTTPException(409, ALIAS_TAKEN_MSG)
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO links (short_code, alias_key, long_url) "
                        "VALUES (:c, :ak, :u) "
                        "RETURNING id, short_code, long_url, click_count, created_at"
                    ),
                    {
                        "c": custom_alias,
                        "ak": normalize_alias(custom_alias),
                        "u": long_url,
                    },
                )
            ).first()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(409, ALIAS_TAKEN_MSG)
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
