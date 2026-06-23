"""add alias_key to links

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-23 00:01:00.000000

Adds a nullable ``alias_key`` column to ``links`` and a unique index on it.

WHY a separate column instead of a functional unique index on short_code
-----------------------------------------------------------------------
Auto-generated short codes use mixed-case base62 (e.g. "aB3x").  A
functional unique index on ``lower(short_code)`` would treat two distinct
auto codes whose lower-case forms collide as duplicates, producing spurious
409 errors.

``alias_key`` is populated **only** for rows created with a user-supplied
custom alias (set to ``normalize_alias(custom_alias)`` = stripped, lowercased,
underscores→hyphens).  Auto-code rows leave it NULL.  Because PostgreSQL
treats NULL values as distinct in UNIQUE constraints, any number of auto-code
rows can coexist without conflict, while two custom aliases that normalise to
the same string are correctly rejected.

Index named ``uq_links_alias_key`` (unique B-tree) replaces the previous
full-scan ``WHERE lower(replace(short_code,'_','-')) = :norm`` expression
used in ``alias_is_taken``, giving a plain index seek on equality lookups.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the nullable alias_key column.
    op.add_column(
        "links",
        sa.Column("alias_key", sa.String(length=16), nullable=True),
    )
    # Unique index (NULL-safe: each NULL is treated as distinct by Postgres).
    op.create_index(
        "uq_links_alias_key",
        "links",
        ["alias_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_links_alias_key", table_name="links")
    op.drop_column("links", "alias_key")
