from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index
from sqlalchemy import Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class Veld2026Raw(Base):
    __tablename__ = "veld_2026_raw_extract"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    fb_listing_id: Mapped[str] = mapped_column(Text, nullable=False)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    seller_profile_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    location_city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    listed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # CDC timestamps — valid_to IS NULL means this is the current version
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name="fk_veld_2026_raw_run_id",
        ),
        Index("idx_veld_2026_raw_fb_listing_id", "fb_listing_id"),
        Index("idx_veld_2026_raw_listed_at", "listed_at"),
        Index("idx_veld_2026_raw_run", "pipeline_run_id"),
        # Unique partial index — enforces one current version per listing ID
        Index(
            "idx_veld_2026_raw_current_listing",
            "fb_listing_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )


class Veld2026Transformed(Base):
    __tablename__ = "veld_2026_transformed"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
        ForeignKeyConstraint(
            ["raw_id"],
            ["veld_2026_raw_extract.id"],
            name="fk_veld_2026_transformed_raw_id",
        ),
        ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name="fk_veld_2026_transformed_run_id",
        ),
        UniqueConstraint("raw_id", name="uq_veld_2026_transformed_raw_id"),
        Index("idx_veld_2026_transformed_location_city", "location_city"),
        Index("idx_veld_2026_transformed_price", "price"),
        Index("idx_veld_2026_transformed_listed_at", "listed_at"),
        Index("idx_veld_2026_transformed_listing_id", "fb_listing_id"),
        Index("idx_veld_2026_transformed_seller", "seller_profile_id"),
        Index("idx_veld_2026_transformed_pipeline_run", "pipeline_run_id"),
    )
