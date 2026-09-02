from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index
from sqlalchemy import Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class SeatGeekListingRaw(Base):
    """Raw CDC record from a SeatGeek API fetch.

    One row per scraped version of a listing. Current version has valid_to IS NULL.
    Keyed on (event_id, sg_listing_id) for CDC uniqueness.

    Unlike Facebook listings, SeatGeek records are already event-matched and
    structured — no Stage 2 classification is needed.
    """

    __tablename__ = "seatgeek_listing_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    sg_listing_id: Mapped[str] = mapped_column(Text, nullable=False)
    sg_event_id: Mapped[int] = mapped_column(Integer, nullable=False)

    section: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    row: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_per_ticket: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    deal_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3), nullable=True)
    delivery_methods: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # CDC timestamps — valid_to IS NULL means this is the current version
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_sg_listing_raw_event_id"),
        ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], name="fk_sg_listing_raw_run_id"),
        Index("idx_sg_listing_raw_event_listing", "event_id", "sg_listing_id"),
        Index("idx_sg_listing_raw_run", "pipeline_run_id"),
        Index(
            "idx_sg_listing_raw_current_listing",
            "event_id",
            "sg_listing_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )
