"""StubHub — Stage 1 extract pipeline.

Reads raw listing items from the Scrapfly scraper and loads them into
stubhub.listing_raw using CDC keyed on (event_id, listing_id).

CDC tracks: raw_price, available_tickets, display_price, is_cheapest.
"""
from __future__ import annotations

import json
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


def _parse_price(val: object) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _parse_created_at(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── CDC helpers ────────────────────────────────────────────────────────────────


_CDC_FIELDS = ("raw_price", "available_tickets", "display_price")

_LOAD_CURRENT = text("""
    SELECT listing_id, raw_price, available_tickets, display_price
    FROM stubhub.listing_raw
    WHERE event_id = :event_id AND valid_to IS NULL
""")

_CLOSE_CURRENT = text("""
    UPDATE stubhub.listing_raw
    SET valid_to = now()
    WHERE event_id = :event_id AND listing_id = :listing_id AND valid_to IS NULL
""")

_INSERT = text("""
    INSERT INTO stubhub.listing_raw (
        event_id, event_key, pipeline_run_id,
        listing_id, section, ticket_class, row,
        seat_from, seat_to, available_tickets, available_quantities,
        raw_price, display_price, total_price, currency,
        face_value, face_value_currency, ticket_type,
        deal_score, star_rating, listing_notes,
        is_cheapest, is_sponsored,
        stubhub_created_at, scraped_at,
        raw_payload, valid_from, valid_to
    ) VALUES (
        :event_id, :event_key, :pipeline_run_id,
        :listing_id, :section, :ticket_class, :row,
        :seat_from, :seat_to, :available_tickets, CAST(:available_quantities AS JSONB),
        :raw_price, :display_price, :total_price, :currency,
        :face_value, :face_value_currency, :ticket_type,
        :deal_score, :star_rating, CAST(:listing_notes AS JSONB),
        :is_cheapest, :is_sponsored,
        :stubhub_created_at, :scraped_at,
        CAST(:raw_payload AS JSONB), now(), NULL
    )
""")


def _load_current_state(session: Session, event_id: uuid.UUID) -> dict[str, dict]:
    rows = session.execute(_LOAD_CURRENT, {"event_id": str(event_id)}).mappings().all()
    return {row["listing_id"]: dict(row) for row in rows}


def _has_changed(existing: dict, params: dict) -> bool:
    for field in _CDC_FIELDS:
        if str(existing.get(field)) != str(params.get(field)):
            return True
    return False


# ── Record mapping ─────────────────────────────────────────────────────────────


def _build_params(
    item: dict,
    run_id: uuid.UUID,
    event_id: uuid.UUID,
    event_key: str,
) -> dict:
    score = item.get("inventoryListingScore") or {}
    notes = [
        n["formattedListingNoteContent"]
        for n in item.get("listingNotes", [])
        if n.get("showToBuyer")
    ]
    return {
        "event_id": str(event_id),
        "event_key": event_key,
        "pipeline_run_id": str(run_id),
        "listing_id": str(item.get("listingId") or item.get("id")),
        "section": item.get("section"),
        "ticket_class": item.get("ticketClassName"),
        "row": item.get("row"),
        "seat_from": item.get("seatFrom"),
        "seat_to": item.get("seatTo"),
        "available_tickets": item.get("availableTickets"),
        "available_quantities": json.dumps(item.get("availableQuantities", [])),
        "raw_price": _parse_price(item.get("rawPrice")),
        "display_price": item.get("price"),
        "total_price": item.get("formattedTotalPrice"),
        "currency": item.get("listingCurrencyCode"),
        "face_value": _parse_price(item.get("faceValue")),
        "face_value_currency": item.get("faceValueCurrencyCode"),
        "ticket_type": item.get("ticketTypeName"),
        "deal_score": score.get("dealScore"),
        "star_rating": _parse_price(score.get("starRating")),
        "listing_notes": json.dumps(notes),
        "is_cheapest": bool(item.get("isCheapestListing", False)),
        "is_sponsored": bool(item.get("isSponsored", False)),
        "stubhub_created_at": _parse_created_at(item.get("createdDateTime")),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_payload": json.dumps(item),
    }


# ── Core CDC logic ─────────────────────────────────────────────────────────────


def _process_records(
    session: Session,
    db_run: PipelineRun,
    items: list[dict],
    result: PipelineResult,
    event_id: uuid.UUID,
    event_key: str,
) -> None:
    current_state = _load_current_state(session, event_id)
    logger.info(
        f"[StubHub Stage1] {len(current_state)} existing current records in DB for this event"
    )

    for item in items:
        result.total += 1
        listing_id = str(item.get("listingId") or item.get("id") or "")
        if not listing_id:
            result.errors += 1
            continue

        params = _build_params(item, db_run.id, event_id, event_key)
        existing = current_state.get(listing_id)

        if existing is None:
            session.execute(_INSERT, params)
            current_state[listing_id] = params
            result.newly_added += 1
        elif _has_changed(existing, params):
            session.execute(
                _CLOSE_CURRENT,
                {"event_id": str(event_id), "listing_id": listing_id},
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
    show_date: Optional[str] = None,
) -> PipelineRun:
    from datetime import date as _date
    parsed_show_date = None
    if show_date:
        try:
            parsed_show_date = _date.fromisoformat(show_date)
        except ValueError:
            pass
    run = PipelineRun(
        stage="stage1_stubhub",
        source=source,
        source_type="stubhub",
        event_key=event_key,
        event_id=event_id,
        mode=mode,
        show_date=parsed_show_date,
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


# ── Entry point ────────────────────────────────────────────────────────────────


def run_from_items(
    items: list[dict],
    source: str,
    event_id: uuid.UUID,
    event_key: str,
    mode: str = "periodic",
    show_date: Optional[str] = None,
) -> PipelineResult:
    logger.info(f"[StubHub Stage1] Starting — source: {source} mode: {mode} show_date: {show_date} ({len(items)} items)")

    with SessionLocal() as session:
        db_run = _create_run(session, source, event_key, event_id, mode, show_date=show_date)
        result = PipelineResult(run_id=db_run.id, status="completed")
        _process_records(session, db_run, items, result, event_id, event_key)
        _finish_run(session, db_run, result)

    logger.info(
        f"[StubHub Stage1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result
