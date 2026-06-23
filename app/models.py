"""Database models."""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    short_code: Mapped[str | None] = mapped_column(
        String(16), unique=True, index=True, nullable=True
    )
    long_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Denormalised counter, updated in batches by the ingestion worker.
    click_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # Normalised alias for uniqueness enforcement (set only for custom aliases).
    # NULLs are ignored by UNIQUE constraints in Postgres, so auto-generated
    # base62 short_codes (which leave this NULL) never collide here.
    # We cannot use a functional unique index on lower(short_code) because
    # base62 codes are mixed-case and two distinct codes could share the same
    # lower() value, causing false conflicts.
    alias_key: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("alias_key", name="uq_links_alias_key"),
    )


class ClickEvent(Base):
    """Raw click events (high write volume, drained from Redis in batches)."""

    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    link_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("links.id", ondelete="CASCADE")
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)
    device: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)

    __table_args__ = (Index("ix_click_events_link_ts", "link_id", "ts"),)


class ClickStatHourly(Base):
    """Pre-aggregated hourly rollups, upserted by the ingestion worker.

    Keeps the analytics dashboard fast no matter how many raw events exist.
    """

    __tablename__ = "click_stats_hourly"

    link_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("links.id", ondelete="CASCADE"), primary_key=True
    )
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0)
