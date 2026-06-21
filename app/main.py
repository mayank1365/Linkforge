"""LinkForge application entrypoint."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers tables on Base.metadata)
from .analytics import ingestion_worker
from .database import Base, engine
from .redis_client import redis_client
from .routers import links, redirect, web

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist (demo convenience; use Alembic in prod).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(ingestion_worker(stop_event))
    app.state.stop_event = stop_event
    app.state.worker_task = worker_task

    yield

    stop_event.set()
    await worker_task
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="LinkForge", version="1.0.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

@app.get("/healthz")
async def healthz():
    try:
        await redis_client.ping()
        return JSONResponse({"status": "ok"})
    except Exception as exc:  # pragma: no cover
        return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=503)


# Order matters: the redirect router owns the "/{short_code}" catch-all, so it
# must be registered last (after the page/API routes and /healthz above).
app.include_router(web.router)
app.include_router(links.router)
app.include_router(redirect.router)
