"""Facebook Marketplace (futurafree actor) — Stage 1 extract pipeline.

Reads actor records and loads them into facebook.facebook_listings_new_raw using CDC
(Change Data Capture) keyed on (event_id, fb_listing_id).

CDC rules:
  - Not in DB            → insert (valid_from=now, valid_to=NULL)
  - Exists, no change    → skip
  - Exists, data changed → close old (valid_to=now), insert new

Output schema from futurafree actor:
  link         — listing URL
  title        — listing title
  price        — string like "$800"
  location     — string like "Toronto, ON"
  image_url    — single image URL string
  id           — listing ID
  sources      — [{"search_term": "...", "timeframe": "..."}]
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from ticket_tracker.db.engine import SessionLocal
from ticket_tracker.db.models.pipeline_tables import PipelineRun


@dataclass
class PipelineResult:
    run_id: uuid.UUID
    status: str
    total: int = 0
    errors: int = 0
    newly_added: int = 0
    change_added: int = 0
    skipped: int = 0


# ── Field parsing ──────────────────────────────────────────────────────────────


def _parse_price(price_str: object) -> Optional[Decimal]:
    """Parse price strings like '$800', '$1,200', '800.00' → Decimal."""
    if price_str is None:
        return None
    try:
        digits = re.sub(r"[^\d.]", "", str(price_str))
        return Decimal(digits).quantize(Decimal("0.01")) if digits else None
    except InvalidOperation:
        return None


def _parse_location(location_str: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split 'Toronto, ON' into (city='Toronto', state='ON').

    Returns (None, None) if the string is missing or unparseable.
    """
    if not location_str:
        return None, None
    parts = [p.strip() for p in location_str.split(",", 1)]
    city = parts[0] or None
    state = parts[1] if len(parts) > 1 else None
    return city, state


# ── CDC helpers ────────────────────────────────────────────────────────────────


_CDC_FIELDS = ("price", "title", "location_city", "location_state")

_LOAD_CURRENT = text("""
    SELECT fb_listing_id, price, title, location_city, location_state
    FROM facebook.facebook_listings_new_raw
    WHERE event_id = :event_id AND valid_to IS NULL
""")

_CLOSE_CURRENT = text("""
    UPDATE facebook.facebook_listings_new_raw
    SET valid_to = now()
    WHERE event_id = :event_id AND fb_listing_id = :fb_listing_id AND valid_to IS NULL
""")

_INSERT = text("""
    INSERT INTO facebook.facebook_listings_new_raw (
        event_id, event_key, pipeline_run_id,
        fb_listing_id, listing_url, seller_id, seller_name,
        title, description, price, currency,
        location_city, location_state, image_urls,
        is_sold, is_pending, listed_at, scraped_at,
        raw_payload, valid_from, valid_to
    ) VALUES (
        :event_id, :event_key, :pipeline_run_id,
        :fb_listing_id, :listing_url, :seller_id, :seller_name,
        :title, :description, :price, :currency,
        :location_city, :location_state, CAST(:image_urls AS JSONB),
        :is_sold, :is_pending, :listed_at, :scraped_at,
        CAST(:raw_payload AS JSONB), now(), NULL
    )
""")


def _load_current_state(session: Session, event_id: uuid.UUID) -> dict[str, dict]:
    rows = session.execute(_LOAD_CURRENT, {"event_id": str(event_id)}).mappings().all()
    return {row["fb_listing_id"]: dict(row) for row in rows}


def _has_changed(existing: dict, params: dict) -> bool:
    for field in _CDC_FIELDS:
        if str(existing.get(field)) != str(params.get(field)):
            return True
    return False


# ── Record mapping ─────────────────────────────────────────────────────────────


def _build_params(
    record: dict,
    run_id: uuid.UUID,
    event_id: uuid.UUID,
    event_key: str,
) -> dict:
    city, state = _parse_location(record.get("location"))
    image_url = record.get("image_url")

    return {
        "event_id": str(event_id),
        "event_key": event_key,
        "pipeline_run_id": str(run_id),
        "fb_listing_id": str(record.get("id")),
        "listing_url": record.get("link"),
        "seller_id": None,
        "seller_name": None,
        "title": record.get("title"),
        "description": None,
        "price": _parse_price(record.get("price")),
        "currency": "CAD",
        "location_city": city,
        "location_state": state,
        "image_urls": json.dumps([image_url] if image_url else []),
        "is_sold": False,
        "is_pending": False,
        "listed_at": None,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_payload": json.dumps(record),
    }


# ── Core CDC logic ─────────────────────────────────────────────────────────────


def _process_records(
    session: Session,
    db_run: PipelineRun,
    records: list[dict],
    result: PipelineResult,
    event_id: uuid.UUID,
    event_key: str,
) -> None:
    current_state = _load_current_state(session, event_id)
    logger.info(
        f"[FB-Mkt Stage1] {len(current_state)} existing current records in DB for this event"
    )

    for record in records:
        result.total += 1
        listing_id = record.get("id")
        if not listing_id:
            result.errors += 1
            logger.debug(f"Skipping record with no listing ID: {record.get('link')!r}")
            continue

        listing_id = str(listing_id)
        params = _build_params(record, db_run.id, event_id, event_key)
        existing = current_state.get(listing_id)

        if existing is None:
            session.execute(_INSERT, params)
            current_state[listing_id] = params
            result.newly_added += 1
        elif _has_changed(existing, params):
            session.execute(
                _CLOSE_CURRENT,
                {"event_id": str(event_id), "fb_listing_id": listing_id},
            )
            session.execute(_INSERT, params)
            current_state[listing_id] = params
            result.change_added += 1
        else:
            result.skipped += 1

    session.commit()


# ── Pipeline run helpers ───────────────────────────────────────────────────────


def _create_run(
    session: Session,
    source: str,
    event_key: str,
    event_id: uuid.UUID,
    mode: str,
) -> PipelineRun:
    run = PipelineRun(
        stage="stage1_facebook_marketplace",
        source=source,
        source_type="facebook_new",
        event_key=event_key,
        event_id=event_id,
        mode=mode,
        status="running",
    )
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


# ── Entry points ───────────────────────────────────────────────────────────────


def run_from_records(
    records: list[dict],
    source: str,
    event_id: uuid.UUID,
    event_key: str,
    mode: str = "periodic",
) -> PipelineResult:
    logger.info(f"[FB-Mkt Stage1] Starting — source: {source} mode: {mode} ({len(records)} records)")

    with SessionLocal() as session:
        db_run = _create_run(session, source, event_key, event_id, mode)
        result = PipelineResult(run_id=db_run.id, status="completed")
        _process_records(session, db_run, records, result, event_id, event_key)
        _finish_run(session, db_run, result)

    logger.info(
        f"[FB-Mkt Stage1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result
