"""Orchestrates the two-stage pipeline and manages pipeline_runs audit records.

Stage 1 — Extract & Load (Bronze):
  Reads an Apify JSON file → validates → upserts to veld_2026_raw.

Stage 2 — Transform & Load (Silver):
  Reads untransformed rows from veld_2026_raw → applies all transformers
  → validates output → inserts into veld_2026_transformed.

Both stages produce a pipeline_runs record and log per-record errors to
pipeline_errors, giving full observability into every run.
"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from ticket_tracker.config import settings
from ticket_tracker.db.engine import SessionLocal
from ticket_tracker.db.models.pipeline_tables import PipelineErrorLog, PipelineRun
from ticket_tracker.pipeline.errors import ErrorCode, PipelineError
from ticket_tracker.pipeline.stage1_extract import loader as s1_loader
from ticket_tracker.pipeline.stage1_extract import reader as s1_reader
from ticket_tracker.pipeline.stage1_extract import validator as s1_validator
from ticket_tracker.pipeline.stage2_transform import loader as s2_loader
from ticket_tracker.pipeline.stage2_transform import reader as s2_reader
from ticket_tracker.pipeline.stage2_transform import validator as s2_validator
from ticket_tracker.pipeline.stage2_transform.transformers import (
    flags,
    location,
    price,
    ticket,
)


# ── Result dataclasses ────────────────────────────────────────────────────────


@dataclass
class StageResult:
    run_id: uuid.UUID
    stage: str
    total: int = 0
    success: int = 0
    errors: int = 0
    skipped: int = 0
    error_breakdown: dict[str, int] = field(default_factory=dict)
    listing_type_counts: dict[str, int] = field(default_factory=dict)


# ── Audit helpers ─────────────────────────────────────────────────────────────


def _create_run(session: Session, stage: str, source_file: str | None) -> PipelineRun:
    run = PipelineRun(
        stage=stage,
        source_file=source_file,
        status="running",
        config={
            "price_min": settings.price_min,
            "price_max": settings.price_max,
            "stage1_batch_size": settings.stage1_batch_size,
            "stage2_batch_size": settings.stage2_batch_size,
        },
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finish_run(session: Session, run: PipelineRun, result: StageResult) -> None:
    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    run.total_records = result.total
    run.success_count = result.success
    run.error_count = result.errors
    run.skipped_count = result.skipped
    run.error_breakdown = result.error_breakdown
    session.commit()


def _log_error(
    session: Session,
    run_id: uuid.UUID,
    stage: str,
    error: PipelineError,
) -> None:
    session.add(
        PipelineErrorLog(
            pipeline_run_id=run_id,
            stage=stage,
            error_code=str(error.error_code),
            error_message=error.message,
            source_identifier=error.source_identifier,
            raw_data=error.raw_data or {},
        )
    )


def _bump_error(result: StageResult, code: str) -> None:
    result.error_breakdown[code] = result.error_breakdown.get(code, 0) + 1


# ── Stage 1 ───────────────────────────────────────────────────────────────────


def run_stage1(file_path: Path) -> StageResult:
    """Read Apify JSON → validate → upsert to veld_2026_raw."""
    logger.info(f"[Stage 1] Starting — source: {file_path.name}")

    with SessionLocal() as session:
        run = _create_run(session, "stage1_extract", file_path.name)
        result = StageResult(run_id=run.id, stage="stage1_extract")

        seen_urls: set[str] = set()
        batch: list[dict] = []
        error_buffer: list[PipelineErrorLog] = []

        def _flush_batch() -> None:
            if batch:
                s1_loader.upsert_batch(session, batch, run.id)
                result.success += len(batch)
                batch.clear()

        def _flush_errors() -> None:
            if error_buffer:
                session.add_all(error_buffer)
                session.commit()
                error_buffer.clear()

        for raw_record, read_error in s1_reader.load_records(file_path):
            result.total += 1

            if read_error is not None:
                result.errors += 1
                _bump_error(result, str(read_error.error_code))
                _log_error(session, run.id, "stage1_extract", read_error)
                if len(error_buffer) >= 50:
                    _flush_errors()
                continue

            url = raw_record.get("url", "")
            if url in seen_urls:
                err = PipelineError(
                    ErrorCode.DUPLICATE_SAME_RUN,
                    f"Duplicate URL in same file: {url}",
                    source_identifier=url,
                )
                result.errors += 1
                _bump_error(result, str(ErrorCode.DUPLICATE_SAME_RUN))
                _log_error(session, run.id, "stage1_extract", err)
                continue
            seen_urls.add(url)

            try:
                s1_validator.validate(raw_record)
            except PipelineError as exc:
                result.errors += 1
                _bump_error(result, str(exc.error_code))
                _log_error(session, run.id, "stage1_extract", exc)
                if len(error_buffer) >= 50:
                    _flush_errors()
                continue

            batch.append(raw_record)
            if len(batch) >= settings.stage1_batch_size:
                _flush_batch()

        _flush_batch()
        _flush_errors()
        _finish_run(session, run, result)

    logger.info(
        f"[Stage 1] Done — total={result.total} success={result.success} "
        f"errors={result.errors}"
    )
    return result


# ── Stage 2 ───────────────────────────────────────────────────────────────────


def _transform_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply all transformers to one raw row and return a merged dict."""
    title = raw.get("title")
    description = raw.get("description")
    search_keyword = raw.get("search_keyword", "veld")

    # 1. Ticket intelligence (needed for quantity before price_per_unit).
    ticket_result = ticket.transform(title)

    # 2. Price.
    price_result = price.transform(
        initial_price=raw.get("initial_price"),
        final_price=raw.get("final_price"),
        quantity=ticket_result.quantity,
        price_min=settings.price_min,
        price_max=settings.price_max,
    )

    # 3. Location.
    loc_result = location.transform(raw.get("location_raw"))

    # 4. Flags.
    flag_result = flags.transform(
        title=title,
        description=description,
        price=price_result.price,
        search_keyword=search_keyword,
    )

    return {
        "raw_id": raw["id"],
        "fb_listing_id": raw["fb_listing_id"],
        "listing_url": raw["listing_url"],
        "seller_profile_id": raw.get("seller_profile_id"),
        "title": title,
        "description": description,
        "currency": raw.get("currency", "CAD"),
        "is_sold": raw.get("is_sold", False),
        "listed_at": raw.get("listed_at"),
        "scraped_at": raw.get("scraped_at"),
        "search_keyword": search_keyword,
        "image_urls": raw.get("image_urls"),
        "condition": raw.get("condition"),
        # Price
        "initial_price": price_result.initial_price,
        "price": price_result.price,
        "price_per_unit": price_result.price_per_unit,
        "price_drop": price_result.price_drop,
        "price_drop_pct": price_result.price_drop_pct,
        "price_is_anomaly": price_result.price_is_anomaly,
        # Location
        "location_raw": raw.get("location_raw"),
        "location_city": loc_result.location_city,
        "location_province": loc_result.location_province,
        "location_region": loc_result.location_region,
        # Ticket
        "quantity": ticket_result.quantity,
        "ticket_type": ticket_result.ticket_type,
        "ticket_type_raw": ticket_result.ticket_type_raw,
        "event_days": ticket_result.event_days,
        # Flags
        "listing_type": flag_result.listing_type,
        "is_relevant": flag_result.is_relevant,
    }


def run_stage2() -> StageResult:
    """Read untransformed raw rows → transform → insert to veld_2026_transformed."""
    logger.info("[Stage 2] Starting")

    with SessionLocal() as session:
        run = _create_run(session, "stage2_transform", None)
        result = StageResult(run_id=run.id, stage="stage2_transform")

        error_buffer: list[PipelineErrorLog] = []

        def _flush_errors() -> None:
            if error_buffer:
                session.add_all(error_buffer)
                session.commit()
                error_buffer.clear()

        for raw_batch in s2_reader.iter_untransformed(
            session, batch_size=settings.stage2_batch_size
        ):
            transformed_batch: list[dict] = []

            for raw in raw_batch:
                result.total += 1
                try:
                    transformed = _transform_record(raw)
                    s2_validator.validate(transformed)
                    transformed_batch.append(transformed)

                    lt = transformed.get("listing_type", "unknown")
                    result.listing_type_counts[lt] = (
                        result.listing_type_counts.get(lt, 0) + 1
                    )
                except PipelineError as exc:
                    result.errors += 1
                    _bump_error(result, str(exc.error_code))
                    _log_error(session, run.id, "stage2_transform", exc)
                    if len(error_buffer) >= 50:
                        _flush_errors()
                except Exception as exc:
                    result.errors += 1
                    _bump_error(result, str(ErrorCode.TRANSFORM_FAILED))
                    pipeline_err = PipelineError(
                        ErrorCode.TRANSFORM_FAILED,
                        f"Unexpected error: {exc}\n{traceback.format_exc()}",
                        source_identifier=str(raw.get("listing_url", "")),
                    )
                    _log_error(session, run.id, "stage2_transform", pipeline_err)
                    if len(error_buffer) >= 50:
                        _flush_errors()

            if transformed_batch:
                s2_loader.insert_batch(session, transformed_batch, run.id)
                result.success += len(transformed_batch)

        _flush_errors()
        _finish_run(session, run, result)

    logger.info(
        f"[Stage 2] Done — total={result.total} success={result.success} "
        f"errors={result.errors}"
    )
    return result
