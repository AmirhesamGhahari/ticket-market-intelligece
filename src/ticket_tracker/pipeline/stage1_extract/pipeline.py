"""Stage 1 extract pipeline.

Reads Apify raider-api records and loads them into veld_2026_raw_extract
using CDC (Change Data Capture) keyed on fb_listing_id.

CDC rules per listing ID:
  - ID not in DB            → insert new record (valid_from=now, valid_to=NULL)
  - ID exists, no change    → skip (already current)
  - ID exists, data changed → close old record (valid_to=now), insert new record
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from ticket_tracker.db.engine import SessionLocal
from ticket_tracker.db.models.pipeline_tables import PipelineRun


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    run_id: uuid.UUID
    status: str
    total: int = 0
    errors: int = 0
    newly_added: int = 0
    change_added: int = 0
    skipped: int = 0


# ── Field parsing ─────────────────────────────────────────────────────────────


def _parse_price(price_str: Optional[str]) -> Optional[Decimal]:
    if not price_str:
        return None
    try:
        digits = re.sub(r"[^\d.]", "", str(price_str))
        return Decimal(digits) if digits else None
    except InvalidOperation:
        return None


def _parse_listed_at(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OSError, ValueError, OverflowError):
        return None


def _parse_fetched_at(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── CDC helpers ───────────────────────────────────────────────────────────────


_CDC_FIELDS = ("price", "is_sold", "title", "location_city", "location_state")


def _load_current_state(session: Session) -> dict[str, dict]:
    """Bulk-load every listing that has a current record (valid_to IS NULL) into memory."""
    rows = session.execute(
        text("""
            SELECT fb_listing_id, price, is_sold, title, location_city, location_state
            FROM veld_2026_raw_extract
            WHERE valid_to IS NULL
        """)
    ).mappings().all()
    return {row["fb_listing_id"]: dict(row) for row in rows}


def _has_changed(existing: dict, params: dict) -> bool:
    for field in _CDC_FIELDS:
        if existing.get(field) != params.get(field):
            return True
    return False


# ── SQL statements ────────────────────────────────────────────────────────────


_INSERT_SQL = text("""
    INSERT INTO veld_2026_raw_extract (
        pipeline_run_id, fb_listing_id, listing_url, seller_profile_id,
        title, description, price, currency,
        location_city, location_state,
        image_urls, is_sold, listed_at, scraped_at,
        raw_payload, valid_from, valid_to
    ) VALUES (
        :pipeline_run_id, :fb_listing_id, :listing_url, :seller_profile_id,
        :title, :description, :price, :currency,
        :location_city, :location_state,
        CAST(:image_urls AS JSONB), :is_sold, :listed_at, :scraped_at,
        CAST(:raw_payload AS JSONB), now(), NULL
    )
""")

_CLOSE_CURRENT_SQL = text("""
    UPDATE veld_2026_raw_extract
    SET valid_to = now()
    WHERE fb_listing_id = :fb_listing_id AND valid_to IS NULL
""")


def _build_params(record: dict, run_id: uuid.UUID) -> dict:
    """Build INSERT params from a raw Apify record."""
    price = record.get("price") or {}
    location = record.get("location") or {}
    image = record.get("primaryImage")
    return {
        "pipeline_run_id": str(run_id),
        "fb_listing_id": record.get("listingId") or record.get("id"),
        "listing_url": record["url"],
        "seller_profile_id": None,
        "title": record.get("title"),
        "description": None,
        "price": _parse_price(price.get("formatted")),
        "currency": price.get("currency"),
        "location_city": location.get("city"),
        "location_state": location.get("state"),
        "image_urls": json.dumps([image] if image else []),
        "is_sold": bool(record.get("isSold", False)),
        "listed_at": _parse_listed_at(record.get("listing_date_ms")),
        "scraped_at": _parse_fetched_at(record.get("_fetchedAt")),
        "raw_payload": json.dumps(record),
    }


# ── Pipeline run helpers ──────────────────────────────────────────────────────


def _create_run(session: Session, source: str) -> PipelineRun:
    run = PipelineRun(stage="stage1", source=source, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finish_run(session: Session, run: PipelineRun, result: PipelineResult) -> None:
    run.status = result.status
    run.finished_at = datetime.now(timezone.utc)
    run.total_records = result.total
    run.error_count = result.errors
    run.newly_added_count = result.newly_added
    run.change_added_count = result.change_added
    run.skipped_count = result.skipped
    session.commit()


# ── Core CDC logic ────────────────────────────────────────────────────────────


def _process_records(
    session: Session,
    db_run: PipelineRun,
    records: list[dict],
    result: PipelineResult,
) -> None:
    current_state = _load_current_state(session)
    logger.info(f"[Stage 1] {len(current_state)} existing current records in DB")

    for record in records:
        result.total += 1

        listing_id = record.get("listingId") or record.get("id")
        if not listing_id:
            result.errors += 1
            logger.debug(f"Skipping record with no listing ID: {record.get('url')!r}")
            continue

        params = _build_params(record, db_run.id)
        existing = current_state.get(listing_id)

        if existing is None:
            session.execute(_INSERT_SQL, params)
            current_state[listing_id] = params
            result.newly_added += 1

        elif _has_changed(existing, params):
            session.execute(_CLOSE_CURRENT_SQL, {"fb_listing_id": listing_id})
            session.execute(_INSERT_SQL, params)
            current_state[listing_id] = params
            result.change_added += 1

        else:
            result.skipped += 1

    session.commit()


# ── Entry points ──────────────────────────────────────────────────────────────


def run(file_path: Path) -> PipelineResult:
    """Run Stage 1 from a saved Apify JSON file (dev / backfill use)."""
    logger.info(f"[Stage 1] Starting — source: {file_path.name}")

    with SessionLocal() as session:
        db_run = _create_run(session, file_path.name)
        result = PipelineResult(run_id=db_run.id, status="completed")

        try:
            with open(file_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                raise ValueError(f"Expected a JSON array, got {type(data).__name__}")
            records = [r for r in data if isinstance(r, dict)]
            if not records:
                raise ValueError("File contains no readable records")
        except Exception as exc:
            result.status = "failed"
            _finish_run(session, db_run, result)
            logger.error(f"[Stage 1] Failed to read file: {exc}")
            return result

        logger.info(f"[Stage 1] Loaded {len(records)} records from file")
        _process_records(session, db_run, records, result)
        _finish_run(session, db_run, result)

    logger.info(
        f"[Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result


def run_from_records(records: list[dict], source: str = "apify") -> PipelineResult:
    """Run Stage 1 from records returned by ApifyRunner (live run)."""
    logger.info(f"[Stage 1] Starting — source: {source} ({len(records)} records)")

    with SessionLocal() as session:
        db_run = _create_run(session, source)
        result = PipelineResult(run_id=db_run.id, status="completed")
        _process_records(session, db_run, records, result)
        _finish_run(session, db_run, result)

    logger.info(
        f"[Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result
