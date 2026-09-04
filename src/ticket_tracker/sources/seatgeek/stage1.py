"""SeatGeek — Stage 1 extract pipeline.

SeatGeek's public API does not expose individual ticket listings — only an
aggregate `stats` object per event (lowest/highest/average price, listing
count). This stage upserts one row per (event, day) into seatgeek_event_stats —
re-running the pipeline the same day overwrites that day's snapshot instead of
appending a new row, giving a daily time series of resale pricing.
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
    fetched: bool = False
    errors: int = 0


def _parse_price(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


_UPSERT_SQL = text("""
    INSERT INTO seatgeek_event_stats (
        event_id, event_key, pipeline_run_id, sg_event_id, stat_date,
        lowest_price, highest_price, average_price, median_price, listing_count,
        raw_payload, fetched_at
    ) VALUES (
        :event_id, :event_key, :pipeline_run_id, :sg_event_id, :stat_date,
        :lowest_price, :highest_price, :average_price, :median_price, :listing_count,
        CAST(:raw_payload AS JSONB), now()
    )
    ON CONFLICT (event_id, stat_date) DO UPDATE SET
        pipeline_run_id = EXCLUDED.pipeline_run_id,
        lowest_price = EXCLUDED.lowest_price,
        highest_price = EXCLUDED.highest_price,
        average_price = EXCLUDED.average_price,
        median_price = EXCLUDED.median_price,
        listing_count = EXCLUDED.listing_count,
        raw_payload = EXCLUDED.raw_payload,
        fetched_at = now()
""")


def _create_run(session: Session, source: str) -> PipelineRun:
    run = PipelineRun(stage="stage1_seatgeek", source=source, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finish_run(session: Session, run: PipelineRun, result: PipelineResult) -> None:
    run.status = result.status
    run.finished_at = datetime.now(timezone.utc)
    run.total_records = 1 if result.fetched else 0
    run.error_count = result.errors
    session.commit()


def run_snapshot(
    event_data: dict,
    source: str,
    event_id: uuid.UUID,
    event_key: str,
    sg_event_id: int,
) -> PipelineResult:
    """Extract the aggregate `stats` object from a SeatGeek event and append a snapshot row."""
    logger.info(f"[SG Stage 1] Starting — source: {source}")

    with SessionLocal() as session:
        db_run = _create_run(session, source)
        result = PipelineResult(run_id=db_run.id, status="completed")

        stats = event_data.get("stats") or {}
        if not stats:
            result.status = "failed"
            result.errors = 1
            _finish_run(session, db_run, result)
            logger.warning(f"[SG Stage 1] No stats object in event {sg_event_id} response — nothing to record")
            return result

        params = {
            "event_id": str(event_id),
            "event_key": event_key,
            "pipeline_run_id": str(db_run.id),
            "sg_event_id": sg_event_id,
            "stat_date": datetime.now(timezone.utc).date(),
            "lowest_price": _parse_price(stats.get("lowest_price")),
            "highest_price": _parse_price(stats.get("highest_price")),
            "average_price": _parse_price(stats.get("average_price")),
            "median_price": _parse_price(stats.get("median_price")),
            "listing_count": stats.get("listing_count"),
            "raw_payload": json.dumps(stats),
        }

        session.execute(_UPSERT_SQL, params)
        session.commit()
        result.fetched = True
        _finish_run(session, db_run, result)

    logger.info(
        f"[SG Stage 1] Done — date={params['stat_date']} lowest={params['lowest_price']} "
        f"highest={params['highest_price']} average={params['average_price']} "
        f"listing_count={params['listing_count']}"
    )
    return result
