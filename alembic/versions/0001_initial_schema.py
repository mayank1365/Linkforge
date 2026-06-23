"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-23 00:00:00.000000

Captures the baseline schema that was previously managed by
``Base.metadata.create_all`` at application start-up:

* links            — core URL-shortener table
* click_events     — raw per-click audit log (high write volume)
* click_stats_hourly — pre-aggregated hourly rollups for fast analytics

No alias_key column yet; that is added in the next migration (0002).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # links
    # ------------------------------------------------------------------
    op.create_table(
        "links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("short_code", sa.String(length=16), nullable=True),
        sa.Column("long_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "click_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("short_code"),
    )
    op.create_index(
        op.f("ix_links_short_code"),
        "links",
        ["short_code"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # click_events
    # ------------------------------------------------------------------
    op.create_table(
        "click_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("link_id", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("device", sa.String(length=16), nullable=True),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.ForeignKeyConstraint(
            ["link_id"],
            ["links.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_click_events_link_ts",
        "click_events",
        ["link_id", "ts"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # click_stats_hourly
    # ------------------------------------------------------------------
    op.create_table(
        "click_stats_hourly",
        sa.Column("link_id", sa.BigInteger(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clicks", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["link_id"],
            ["links.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("link_id", "bucket"),
    )


def downgrade() -> None:
    op.drop_table("click_stats_hourly")
    op.drop_index("ix_click_events_link_ts", table_name="click_events")
    op.drop_table("click_events")
    op.drop_index(op.f("ix_links_short_code"), table_name="links")
    op.drop_table("links")
