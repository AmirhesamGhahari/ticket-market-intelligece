"""Facebook Marketplace — Stage 1 extract pipeline.

Reads Apify raider-api records and loads them into facebook_listing_raw
using CDC (Change Data Capture) keyed on (event_id, fb_listing_id).

CDC rules per listing:
  - Not in DB            → insert new record (valid_from=now, valid_to=NULL)
  - Exists, no change    → skip
  - Exists, data changed → close old record (valid_to=now), insert new record
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


def _load_current_state(session: Session, event_id: uuid.UUID) -> dict[str, dict]:
    rows = session.execute(
        text("""
            SELECT fb_listing_id, price, is_sold, title, location_city, location_state
            FROM facebook_listing_raw
            WHERE event_id = :event_id AND valid_to IS NULL
        """),
        {"event_id": str(event_id)},
    ).mappings().all()
    return {row["fb_listing_id"]: dict(row) for row in rows}


def _has_changed(existing: dict, params: dict) -> bool:
    for field in _CDC_FIELDS:
        if existing.get(field) != params.get(field):
            return True
    return False


# ── SQL statements ────────────────────────────────────────────────────────────


_INSERT_SQL = text("""
    INSERT INTO facebook_listing_raw (
        event_id, event_key, pipeline_run_id, fb_listing_id, listing_url, seller_profile_id,
        title, description, price, currency,
        location_city, location_state,
        image_urls, is_sold, listed_at, scraped_at,
        raw_payload, valid_from, valid_to
    ) VALUES (
        :event_id, :event_key, :pipeline_run_id, :fb_listing_id, :listing_url, :seller_profile_id,
        :title, :description, :price, :currency,
        :location_city, :location_state,
        CAST(:image_urls AS JSONB), :is_sold, :listed_at, :scraped_at,
        CAST(:raw_payload AS JSONB), now(), NULL
    )
""")

_CLOSE_CURRENT_SQL = text("""
    UPDATE facebook_listing_raw
    SET valid_to = now()
    WHERE event_id = :event_id AND fb_listing_id = :fb_listing_id AND valid_to IS NULL
""")


def _build_params(record: dict, run_id: uuid.UUID, event_id: uuid.UUID, event_key: str) -> dict:
    price = record.get("price") or {}
    location = record.get("location") or {}
    image = record.get("primaryImage")
    return {
        "event_id": str(event_id),
        "event_key": event_key,
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
    run = PipelineRun(stage="stage1_facebook", source=source, status="running")
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
    event_id: uuid.UUID,
    event_key: str,
) -> None:
    current_state = _load_current_state(session, event_id)
    logger.info(f"[FB Stage 1] {len(current_state)} existing current records in DB for this event")

    for record in records:
        result.total += 1

        listing_id = record.get("listingId") or record.get("id")
        if not listing_id:
            result.errors += 1
            logger.debug(f"Skipping record with no listing ID: {record.get('url')!r}")
            continue

        params = _build_params(record, db_run.id, event_id, event_key)
        existing = current_state.get(listing_id)

        if existing is None:
            session.execute(_INSERT_SQL, params)
            current_state[listing_id] = params
            result.newly_added += 1

        elif _has_changed(existing, params):
            session.execute(_CLOSE_CURRENT_SQL, {"event_id": str(event_id), "fb_listing_id": listing_id})
            session.execute(_INSERT_SQL, params)
            current_state[listing_id] = params
            result.change_added += 1

        else:
            result.skipped += 1

    session.commit()


# ── Entry points ──────────────────────────────────────────────────────────────


def run(file_path: Path, event_id: uuid.UUID, event_key: str) -> PipelineResult:
    """Run Stage 1 from a saved Apify JSON file (dev / backfill use)."""
    logger.info(f"[FB Stage 1] Starting — source: {file_path.name}")

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
            logger.error(f"[FB Stage 1] Failed to read file: {exc}")
            return result

        logger.info(f"[FB Stage 1] Loaded {len(records)} records from file")
        _process_records(session, db_run, records, result, event_id, event_key)
        _finish_run(session, db_run, result)

    logger.info(
        f"[FB Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result


def run_from_records(records: list[dict], source: str, event_id: uuid.UUID, event_key: str) -> PipelineResult:
    """Run Stage 1 from records returned by ApifyRunner (live run)."""
    logger.info(f"[FB Stage 1] Starting — source: {source} ({len(records)} records)")

    with SessionLocal() as session:
        db_run = _create_run(session, source)
        result = PipelineResult(run_id=db_run.id, status="completed")
        _process_records(session, db_run, records, result, event_id, event_key)
        _finish_run(session, db_run, result)

    logger.info(
        f"[FB Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result
