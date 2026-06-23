"""Application settings, loaded from environment / .env."""
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infrastructure
    database_url: str = "postgresql+asyncpg://linkforge:linkforge@localhost:5432/linkforge"
    redis_url: str = "redis://localhost:6379/0"
    base_url: str = "http://localhost:8000"

    # Cache
    cache_ttl_seconds: int = 3600

    # Distributed rate limiter (token bucket, per client IP)
    rate_limit_capacity: int = 20      # burst size
    rate_limit_refill: float = 5.0     # tokens per second

    # Short code generation
    short_code_offset: int = 100_000   # so the first code isn't "0"/"1"

    # Async click ingestion worker
    ingest_batch_size: int = 500
    ingest_interval: float = 0.25      # seconds to sleep when queue is empty

    @model_validator(mode="after")
    def _normalize_for_hosting(self):
        # Managed Postgres (Render/Heroku/etc.) hands out a sync-driver URL like
        # postgres:// or postgresql://. Force the asyncpg driver our app uses.
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            pass
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        elif url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        # asyncpg rejects the libpq "sslmode" query param; drop it if present.
        if "?" in url:
            base, _, query = url.partition("?")
            kept = [p for p in query.split("&") if not p.lower().startswith("sslmode")]
            url = base + ("?" + "&".join(kept) if kept else "")
        self.database_url = url

        # On Render the public URL is injected; use it so short links are shareable.
        external = os.environ.get("RENDER_EXTERNAL_URL")
        if external:
            self.base_url = external.rstrip("/")
        return self


settings = Settings()
