from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index
from sqlalchemy import Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class FacebookListingTransformed(Base):
    """Transformed and enriched version of a raw Facebook Marketplace listing.

    One row per raw record (raw_id is unique). Transformation logic lives in
    Stage 2 SQL: quantity extraction, ticket type classification, price anomaly
    flagging, event day detection, and is_relevant scoring.
    """

    __tablename__ = "transformed"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    raw_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    fb_listing_id: Mapped[str] = mapped_column(Text, nullable=False)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    seller_profile_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CAD")
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    listed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    image_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    price_per_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    price_is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    location_city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_state: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ticket_type: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    event_days: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    listing_type: Mapped[str] = mapped_column(String(32), nullable=False, default="resale")
    is_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_transformed_event_id"),
        ForeignKeyConstraint(["raw_id"], ["raw_extract.id"], name="fk_transformed_raw_id"),
        ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], name="fk_transformed_run_id"),
        UniqueConstraint("raw_id", name="uq_transformed_raw_id"),
        # Compound leading indexes — event_id first
        Index("idx_transformed_event_city", "event_id", "location_city"),
        Index("idx_transformed_event_price", "event_id", "price"),
        Index("idx_transformed_event_listed_at", "event_id", "listed_at"),
        Index("idx_transformed_event_listing_id", "event_id", "fb_listing_id"),
        Index("idx_transformed_seller", "seller_profile_id"),
        Index("idx_transformed_pipeline_run", "pipeline_run_id"),
    )
