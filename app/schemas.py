"""Pydantic request/response schemas for the JSON API."""
import re
from datetime import datetime

from pydantic import BaseModel, HttpUrl, field_validator

# Letters, numbers, hyphen and underscore — matches the UI placeholder ("my-link").
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
# Aliases that would shadow real routes and never resolve as a short link.
RESERVED_ALIASES = {
    "api", "dashboard", "static", "healthz", "htmx", "favicon.ico", "robots.txt",
}


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
        if not ALIAS_RE.match(v):
            raise ValueError(
                "alias may contain only letters, numbers, hyphen or underscore "
                "(max 16 characters)"
            )
        if v.lower() in RESERVED_ALIASES:
            raise ValueError("that alias is reserved")
        return v


class LinkOut(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    click_count: int
    created_at: datetime
