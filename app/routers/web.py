"""Server-rendered pages and HTMX partials (no JS framework)."""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import analytics
from ..config import settings
from ..database import SessionLocal, get_session
from ..ratelimit import client_ip, check_rate_limit
from ..schemas import CreateLink
from .helpers import create_link_record

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
    except Exception:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"message": "Please enter a valid http(s) URL (and a clean alias)."},
            status_code=422,
        )

    async with SessionLocal() as session:
        try:
            row = await create_link_record(
                session, str(payload.long_url), payload.custom_alias
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                message = (
                    f"The alias “{payload.custom_alias}” is already in use — "
                    "please choose a different one."
                )
            else:
                message = str(exc.detail)
            return templates.TemplateResponse(
                request,
                "partials/error.html",
                {"message": message},
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
