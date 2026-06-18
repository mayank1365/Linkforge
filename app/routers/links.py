"""JSON REST API for link management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from ..ratelimit import rate_limit_dependency
from ..schemas import CreateLink, LinkOut
from .helpers import create_link_record

router = APIRouter(prefix="/api", tags=["links"])


@router.post(
    "/links",
    response_model=LinkOut,
    dependencies=[Depends(rate_limit_dependency)],
)
async def create_link(payload: CreateLink) -> LinkOut:
    async with SessionLocal() as session:
        row = await create_link_record(
            session, str(payload.long_url), payload.custom_alias
        )
    return LinkOut(
        short_code=row.short_code,
        short_url=f"{settings.base_url}/{row.short_code}",
        long_url=row.long_url,
        click_count=row.click_count,
        created_at=row.created_at,
    )


@router.get("/links/{short_code}", response_model=LinkOut)
async def get_link(short_code: str) -> LinkOut:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT short_code, long_url, click_count, created_at "
                    "FROM links WHERE short_code = :c"
                ),
                {"c": short_code},
            )
        ).first()
    if not row:
        raise HTTPException(404, "link not found")
    return LinkOut(
        short_code=row.short_code,
        short_url=f"{settings.base_url}/{row.short_code}",
        long_url=row.long_url,
        click_count=row.click_count,
        created_at=row.created_at,
    )
