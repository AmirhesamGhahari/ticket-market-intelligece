"""Stage 1 extract pipeline.

Reads a BrightData JSON file and loads records into veld_2026_raw_extract
using CDC (Change Data Capture) based on listing URL.

CDC rules per URL:
  - URL not in DB           → insert new record (valid_from=now, valid_to=NULL)
  - URL exists, no change   → skip (already current)
  - URL exists, data changed → close old record (valid_to=now), insert new record
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


def _extract_listing_id(url: str) -> Optional[str]:
    """Return the numeric listing ID from a Facebook Marketplace URL, or None."""
    segment = url.rstrip("/").rsplit("/", 1)[-1]
    return segment if segment.isdigit() else None


def _parse_price(price_str: Optional[str]) -> Optional[Decimal]:
    if not price_str:
        return None
    try:
        digits = re.sub(r"[^\d.]", "", price_str)
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


# ── CDC helpers ───────────────────────────────────────────────────────────────


# Fields compared to decide whether a listing has changed between runs.
_CDC_FIELDS = ("price", "is_sold", "title", "location_city", "location_state")


def _load_current_state(session: Session) -> dict[str, dict]:
    """Bulk-load every URL that has a current record (valid_to IS NULL) into memory."""
    rows = session.execute(
        text("""
            SELECT listing_url, price, is_sold, title, location_city, location_state
            FROM veld_2026_raw_extract
            WHERE valid_to IS NULL
        """)
    ).mappings().all()
    return {row["listing_url"]: dict(row) for row in rows}


def _has_changed(existing: dict, params: dict) -> bool:
    for field in _CDC_FIELDS:
        e = existing.get(field)
        n = params.get(field)
        if e != n:
            return True
    return False


# ── SQL statements ────────────────────────────────────────────────────────────


_INSERT_SQL = text("""
    INSERT INTO veld_2026_raw_extract (
        pipeline_run_id, fb_listing_id, listing_url, seller_profile_id,
        title, description, price, location_city, location_state,
        image_urls, is_sold, listed_at, scraped_at, raw_payload,
        valid_from, valid_to
    ) VALUES (
        :pipeline_run_id, :fb_listing_id, :listing_url, :seller_profile_id,
        :title, :description, :price, :location_city, :location_state,
        :image_urls::jsonb, :is_sold, :listed_at, :scraped_at, :raw_payload::jsonb,
        now(), NULL
    )
""")

_CLOSE_CURRENT_SQL = text("""
    UPDATE veld_2026_raw_extract
    SET valid_to = now()
    WHERE listing_url = :listing_url AND valid_to IS NULL
""")


def _build_params(record: dict, run_id: uuid.UUID, listing_id: str) -> dict:
    image = record.get("primaryImage")
    return {
        "pipeline_run_id": str(run_id),
        "fb_listing_id": listing_id,
        "listing_url": record["url"],
        "seller_profile_id": None,
        "title": record.get("title"),
        "description": None,
        "price": _parse_price(record.get("price.formatted")),
        "location_city": record.get("location.city"),
        "location_state": record.get("location.state"),
        "image_urls": json.dumps([image] if image else []),
        "is_sold": bool(record.get("isSold", False)),
        "listed_at": _parse_listed_at(record.get("listing_date_ms")),
        "scraped_at": None,
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


# ── Entry point ───────────────────────────────────────────────────────────────


def run(file_path: Path) -> PipelineResult:
    """Run Stage 1: read BrightData file → CDC upsert into veld_2026_raw_extract.

    Steps:
      1. Create pipeline_run record (status="running").
      2. Open and parse the file — fail fast if unreadable or empty.
      3. Bulk-load current DB state (all rows with valid_to IS NULL) into memory.
      4. For each record:
           a. Extract numeric listing ID from URL — count as error and skip if missing.
           b. CDC: new URL → insert. Unchanged → skip. Changed → close old, insert new.
      5. Finalize pipeline_run with counts and status.
    """
    logger.info(f"[Stage 1] Starting — source: {file_path.name}")

    with SessionLocal() as session:
        db_run = _create_run(session, file_path.name)
        result = PipelineResult(run_id=db_run.id, status="completed")

        # Step 2 — read file
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

        # Step 3 — snapshot current DB state
        current_state = _load_current_state(session)
        logger.info(f"[Stage 1] {len(current_state)} existing current records in DB")

        # Step 4 — process records one by one
        for record in records:
            result.total += 1
            url = record.get("url") or ""

            listing_id = _extract_listing_id(url)
            if not listing_id:
                result.errors += 1
                logger.debug(f"Skipping record with invalid URL: {url!r}")
                continue

            params = _build_params(record, db_run.id, listing_id)
            existing = current_state.get(url)

            if existing is None:
                # New listing — insert
                session.execute(_INSERT_SQL, params)
                result.newly_added += 1

            elif _has_changed(existing, params):
                # Listing changed — close old version, insert new
                session.execute(_CLOSE_CURRENT_SQL, {"listing_url": url})
                session.execute(_INSERT_SQL, params)
                result.change_added += 1

            else:
                # No change — already current
                result.skipped += 1

        session.commit()

        # Step 5 — finalize run record
        _finish_run(session, db_run, result)

    logger.info(
        f"[Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result
