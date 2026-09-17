from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index
from sqlalchemy import Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class FacebookListingsNewClassified(Base):
    """LLM classification result for a facebook.facebook_listings_new_raw row.

    One row per raw listing (enforced by unique constraint on raw_listing_id).
    Mirrors the structure of the legacy FacebookListingsLegacyClassified.
    """

    __tablename__ = "facebook_listings_new_classified"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    raw_listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)

    is_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_buyer_listing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_merch: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_wrong_category: Mapped[bool] = mapped_column(Boolean, nullable=False)

    extracted_event: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    face_value_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    face_value_mentioned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ticket_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    event_days: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    price_negotiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    includes_extras: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    seller_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_llm_response: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["raw_listing_id"],
            ["facebook.facebook_listings_new_raw.id"],
            name="fk_fb_mkt_classified_raw",
        ),
        UniqueConstraint("raw_listing_id", name="uq_fb_mkt_classified_raw_listing"),
        Index("idx_fb_mkt_classified_is_ticket", "is_ticket"),
        Index("idx_fb_mkt_classified_classified_at", "classified_at"),
        Index("idx_fb_mkt_classified_raw_listing_id", "raw_listing_id"),
        {"schema": "facebook"},
    )
