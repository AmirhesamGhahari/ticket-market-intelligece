from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKeyConstraint, Index
from sqlalchemy import Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class SeatGeekEventStats(Base):
    """Aggregate price-trend snapshot from a SeatGeek API fetch, one row per event per day.

    SeatGeek's public API does not expose individual ticket listings —
    only event-level aggregate stats (lowest/highest/average price, listing
    count). Every pipeline run upserts the row for (event_id, stat_date),
    so re-running the same day overwrites that day's snapshot instead of
    appending a new row, giving a daily time series of resale pricing.
    """

    __tablename__ = "seatgeek_event_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    sg_event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)

    lowest_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    highest_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    average_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    median_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    listing_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_sg_event_stats_event_id"),
        ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], name="fk_sg_event_stats_run_id"),
        UniqueConstraint("event_id", "stat_date", name="uq_sg_event_stats_event_date"),
        Index("idx_sg_event_stats_run", "pipeline_run_id"),
    )
