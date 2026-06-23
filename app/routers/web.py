"""Server-rendered pages and HTMX partials (no JS framework)."""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .. import analytics
from ..config import settings
from ..database import SessionLocal, get_session
from ..ratelimit import client_ip, check_rate_limit
from ..schemas import ALIAS_RE, RESERVED_ALIASES, CreateLink
from .helpers import ALIAS_TAKEN_MSG, alias_is_taken, create_link_record

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.post("/htmx/shorten", response_class=HTMLResponse)
async def htmx_shorten(
    request: Request,
    long_url: str = Form(...),
    custom_alias: str = Form(""),
):
    ip = client_ip(request)
    allowed, _ = await check_rate_limit(f"api:{ip}")
    if not allowed:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"message": "Rate limit exceeded — slow down a moment."},
            status_code=429,
        )

    # Validate via the same schema the JSON API uses.
    try:
        payload = CreateLink(long_url=long_url, custom_alias=custom_alias or None)
    except ValidationError as exc:
        alias_errors = [
            err for err in exc.errors()
            if err.get("loc") and err["loc"][0] == "custom_alias"
        ]
        if alias_errors:
            # Surface the validator's own message (covers format + reserved cases).
            raw = alias_errors[0].get("msg", "").split("Value error, ", 1)[-1]
            message = (raw[:1].upper() + raw[1:] + ".") if raw else "Invalid alias."
        else:
            message = "Please enter a valid http or https URL."
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"message": message},
            status_code=422,
        )

    async with SessionLocal() as session:
        try:
            row = await create_link_record(
                session, str(payload.long_url), payload.custom_alias
            )
        except HTTPException as exc:
            # The helper already crafts a clear, alias-specific 409 message.
            return templates.TemplateResponse(
                request,
                "partials/error.html",
                {"message": str(exc.detail)},
                status_code=exc.status_code,
            )
        except Exception:
            return templates.TemplateResponse(
                request,
                "partials/error.html",
                {"message": "Something went wrong creating your link. Please try again."},
                status_code=500,
            )

    return templates.TemplateResponse(
        request,
        "partials/link_result.html",
        {
            "short_url": f"{settings.base_url}/{row.short_code}",
            "short_code": row.short_code,
            "long_url": row.long_url,
        },
    )


@router.get("/htmx/check-alias", response_class=HTMLResponse)
async def check_alias(
    request: Request,
    custom_alias: str = "",
    session=Depends(get_session),
):
    """Live alias availability check (called as the user types).

    Renders an inline message under the field and an out-of-band swap that
    enables/disables the Shorten button.
    """
    alias = custom_alias.strip()

    if not alias:
        state, message = "empty", ""
    elif not ALIAS_RE.match(alias):
        state, message = (
            "error",
            "Alias may contain only letters, numbers, hyphen or underscore (max 16).",
        )
    elif alias.lower() in RESERVED_ALIASES:
        state, message = "error", "That alias is reserved. Please choose another."
    elif await alias_is_taken(session, alias):
        state, message = "error", ALIAS_TAKEN_MSG
    else:
        state, message = "ok", "Available"

    return templates.TemplateResponse(
        request,
        "partials/alias_feedback.html",
        {"state": state, "message": message},
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session=Depends(get_session)):
    overview = await analytics.get_overview(session)
    series = await analytics.get_hourly_series(session)
    top = await analytics.get_top_links(session)
    devices = await analytics.get_device_breakdown(session)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "overview": overview,
            "series": series,
            "top": top,
            "devices": devices,
            "max_clicks": max((p["clicks"] for p in series), default=1),
        },
    )


@router.get("/htmx/stats", response_class=HTMLResponse)
async def htmx_stats(request: Request, session=Depends(get_session)):
    """Polled by HTMX every couple of seconds for live numbers."""
    overview = await analytics.get_overview(session)
    series = await analytics.get_hourly_series(session)
    top = await analytics.get_top_links(session)
    devices = await analytics.get_device_breakdown(session)
    return templates.TemplateResponse(
        request,
        "partials/stats.html",
        {
            "overview": overview,
            "series": series,
            "top": top,
            "devices": devices,
            "max_clicks": max((p["clicks"] for p in series), default=1),
        },
    )
