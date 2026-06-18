"""Pydantic request/response schemas for the JSON API."""
from datetime import datetime

from pydantic import BaseModel, HttpUrl, field_validator


class CreateLink(BaseModel):
    long_url: HttpUrl
    custom_alias: str | None = None

    @field_validator("custom_alias")
    @classmethod
    def _validate_alias(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.isalnum() or len(v) > 16:
            raise ValueError("alias must be alphanumeric and at most 16 chars")
        return v


class LinkOut(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    click_count: int
    created_at: datetime
