"""Alembic environment — runs async using the app's existing asyncpg engine.

We reuse ``app.database.engine`` (already configured with the correct
``postgresql+asyncpg://`` URL from ``app.config.settings``) so there is no
need for a separate sync driver (psycopg2 is *not* installed).

Offline mode emits SQL to stdout — useful for reviewing or piping to psql.
Online mode uses ``AsyncConnection.run_sync`` to drive the sync Alembic API
over the async connection.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ---------------------------------------------------------------------------
# Alembic config object — provides access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging from the ini file (if we have one).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Pull the database URL and target metadata from the application itself so
# there is a single source of truth.
# ---------------------------------------------------------------------------
from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (registers all tables on Base.metadata)

# Inject the URL into Alembic's config so offline mode can use it too.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migration — generates SQL without a live DB connection.
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Emit migration SQL to stdout (no live DB required)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Render CREATE / DROP with IF NOT EXISTS / IF EXISTS so re-runs are safe.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration — connects to the live DB and applies changes.
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
