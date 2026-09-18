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


class StubHubListingRaw(Base):
    """Raw CDC record from a StubHub Scrapfly scrape run.

    Lives in the 'stubhub' schema. CDC key is (event_id, listing_id).
    Tracks price and availability changes over time.
    """

    __tablename__ = "listing_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    listing_id: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ticket_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    row: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seat_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seat_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    available_tickets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    available_quantities: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    raw_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    display_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    face_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    face_value_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    ticket_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deal_score: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    star_rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    listing_notes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    is_cheapest: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_sponsored: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    stubhub_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id"], ["events.id"],
            name="fk_sh_listing_raw_event_id",
        ),
        ForeignKeyConstraint(
            ["pipeline_run_id"], ["pipeline_runs.id"],
            name="fk_sh_listing_raw_run_id",
        ),
        Index("idx_sh_listing_raw_event_listing", "event_id", "listing_id"),
        Index("idx_sh_listing_raw_event_price", "event_id", "raw_price"),
        Index("idx_sh_listing_raw_run", "pipeline_run_id"),
        Index(
            "idx_sh_listing_raw_current_listing",
            "event_id",
            "listing_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"schema": "stubhub"},
    )
