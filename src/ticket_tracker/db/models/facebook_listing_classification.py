from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class FacebookListingClassification(Base):
    __tablename__ = "facebook_listing_classifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    raw_listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("facebook_listing_raw.id", name="fk_fb_classification_raw"),
        nullable=False,
    )

    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Core verdicts ─────────────────────────────────────────────────────────
    is_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_buyer_listing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_merch: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_wrong_category: Mapped[bool] = mapped_column(Boolean, nullable=False)  # unrelated items (appliances, pest control)

    # ── Extracted event info ───────────────────────────────────────────────────
    extracted_event: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    face_value_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)   # seller's original purchase price
    face_value_mentioned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ticket_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # VIP, GA, WEEKEND_PASS, DAY_PASS, UNKNOWN
    event_days: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)        # ["Friday", "Saturday"]

    # ── Offer details ─────────────────────────────────────────────────────────
    price_negotiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    includes_extras: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # ["parking_pass", "camping_pass", "hotel"]

    # ── Seller notes ──────────────────────────────────────────────────────────
    seller_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # transfer method, urgency, condition

    # ── Meta ──────────────────────────────────────────────────────────────────
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)   # high, medium, low
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_llm_response: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("raw_listing_id", name="uq_fb_classification_raw_listing"),
        Index("idx_fb_classification_is_ticket", "is_ticket"),
        Index("idx_fb_classification_classified_at", "classified_at"),
        Index("idx_fb_classification_raw_listing_id", "raw_listing_id"),
    )
