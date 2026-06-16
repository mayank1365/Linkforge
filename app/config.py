"""Application settings, loaded from environment / .env."""
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


settings = Settings()
