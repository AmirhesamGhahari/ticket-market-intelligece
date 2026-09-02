"""SeatGeek — Stage 1 extract pipeline.

Reads SeatGeek listings API records and loads them into seatgeek_listing_raw
using CDC (Change Data Capture) keyed on (event_id, sg_listing_id).

CDC rules per listing:
  - Not in DB            → insert new record (valid_from=now, valid_to=NULL)
  - Exists, no change    → skip
  - Exists, data changed → close old record (valid_to=now), insert new record

No Stage 2 classification needed — SeatGeek listings are already event-matched
and structured (section, row, price per ticket, quantity).
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


def _parse_price(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_deal_score(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return max(Decimal("0"), min(Decimal("1"), d))
    except InvalidOperation:
        return None


# ── CDC helpers ───────────────────────────────────────────────────────────────


_CDC_FIELDS = ("price_per_ticket", "quantity")


def _load_current_state(session: Session, event_id: uuid.UUID) -> dict[str, dict]:
    rows = session.execute(
        text("""
            SELECT sg_listing_id, price_per_ticket, quantity
            FROM seatgeek_listing_raw
            WHERE event_id = :event_id AND valid_to IS NULL
        """),
        {"event_id": str(event_id)},
    ).mappings().all()
    return {row["sg_listing_id"]: dict(row) for row in rows}


def _has_changed(existing: dict, params: dict) -> bool:
    for field in _CDC_FIELDS:
        existing_val = existing.get(field)
        new_val = params.get(field)
        if existing_val is None and new_val is None:
            continue
        if existing_val is None or new_val is None:
            return True
        if Decimal(str(existing_val)) != Decimal(str(new_val)):
            return True
    return False


# ── SQL statements ────────────────────────────────────────────────────────────


_INSERT_SQL = text("""
    INSERT INTO seatgeek_listing_raw (
        event_id, event_key, pipeline_run_id,
        sg_listing_id, sg_event_id,
        section, row, quantity, price_per_ticket, deal_score,
        delivery_methods, raw_payload, valid_from, valid_to
    ) VALUES (
        :event_id, :event_key, :pipeline_run_id,
        :sg_listing_id, :sg_event_id,
        :section, :row, :quantity, :price_per_ticket, :deal_score,
        CAST(:delivery_methods AS JSONB), CAST(:raw_payload AS JSONB), now(), NULL
    )
""")

_CLOSE_CURRENT_SQL = text("""
    UPDATE seatgeek_listing_raw
    SET valid_to = now()
    WHERE event_id = :event_id AND sg_listing_id = :sg_listing_id AND valid_to IS NULL
""")


def _build_params(
    record: dict,
    run_id: uuid.UUID,
    event_id: uuid.UUID,
    event_key: str,
    sg_event_id: int,
) -> dict:
    delivery = record.get("delivery") or {}
    methods = delivery.get("methods") or []
    price = (
        _parse_price(record.get("price"))
        or _parse_price(record.get("display_price"))
        or _parse_price(record.get("actual_price"))
    )
    return {
        "event_id": str(event_id),
        "event_key": event_key,
        "pipeline_run_id": str(run_id),
        "sg_listing_id": str(record["id"]),
        "sg_event_id": sg_event_id,
        "section": record.get("section"),
        "row": record.get("row"),
        "quantity": int(record.get("quantity") or 1),
        "price_per_ticket": price,
        "deal_score": _parse_deal_score(record.get("deal_score")),
        "delivery_methods": json.dumps(methods),
        "raw_payload": json.dumps(record),
    }


# ── Pipeline run helpers ──────────────────────────────────────────────────────


def _create_run(session: Session, source: str) -> PipelineRun:
    run = PipelineRun(stage="stage1_seatgeek", source=source, status="running")
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
    sg_event_id: int,
) -> None:
    current_state = _load_current_state(session, event_id)
    logger.info(f"[SG Stage 1] {len(current_state)} existing current records in DB for this event")

    for record in records:
        result.total += 1

        listing_id = record.get("id")
        if not listing_id:
            result.errors += 1
            logger.debug(f"[SG Stage 1] Skipping record with no id: {record!r}")
            continue

        price = (
            _parse_price(record.get("price"))
            or _parse_price(record.get("display_price"))
            or _parse_price(record.get("actual_price"))
        )
        if price is None:
            result.errors += 1
            logger.debug(f"[SG Stage 1] Skipping listing {listing_id} — no parseable price")
            continue

        params = _build_params(record, db_run.id, event_id, event_key, sg_event_id)
        existing = current_state.get(str(listing_id))

        if existing is None:
            session.execute(_INSERT_SQL, params)
            current_state[str(listing_id)] = params
            result.newly_added += 1

        elif _has_changed(existing, params):
            session.execute(_CLOSE_CURRENT_SQL, {"event_id": str(event_id), "sg_listing_id": str(listing_id)})
            session.execute(_INSERT_SQL, params)
            current_state[str(listing_id)] = params
            result.change_added += 1

        else:
            result.skipped += 1

    session.commit()


# ── Entry point ───────────────────────────────────────────────────────────────


def run_from_records(
    records: list[dict],
    source: str,
    event_id: uuid.UUID,
    event_key: str,
    sg_event_id: int,
) -> PipelineResult:
    """Run Stage 1 SeatGeek from records returned by SeatGeekClient."""
    logger.info(f"[SG Stage 1] Starting — source: {source} ({len(records)} records)")

    with SessionLocal() as session:
        db_run = _create_run(session, source)
        result = PipelineResult(run_id=db_run.id, status="completed")
        _process_records(session, db_run, records, result, event_id, event_key, sg_event_id)
        _finish_run(session, db_run, result)

    logger.info(
        f"[SG Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} change_added={result.change_added} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return result
