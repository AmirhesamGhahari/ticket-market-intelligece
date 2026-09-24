from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKeyConstraint, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ticket_tracker.db.base import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Which pipeline stage ran (e.g. "stage1_stubhub", "stage1_facebook_new")
    stage: Mapped[str] = mapped_column(String(64), nullable=False)

    # Config name — the YAML file used (e.g. "olivia_rodrigo_toronto_oct2026")
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Scraper used — "facebook_legacy" | "facebook_new" | "stubhub" | "seatgeek"
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Run mode — "initial" (first full scrape) or "periodic"
    mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Event this run belongs to (denormalized for easy filtering)
    event_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True)

    # For multi-date events: which specific show date this run covers (StubHub only)
    show_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    total_records: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    newly_added_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    change_added_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    skipped_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id"], ["events.id"],
            name="fk_pipeline_runs_event_id",
        ),
        Index("idx_pipeline_runs_lstarted_at",  "started_at"),
        Index("idx_pipeline_runs_created_at",   "created_at"),
        Index("idx_pipeline_runs_event_key",    "event_key"),
        Index("idx_pipeline_runs_event_id",     "event_id"),
        Index("idx_pipeline_runs_source_type",  "source_type"),
        Index("idx_pipeline_runs_show_date",    "show_date"),
    )
