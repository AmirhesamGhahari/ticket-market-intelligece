from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from ticket_tracker.db.engine import SessionLocal
from ticket_tracker.db.models.facebook_listing_classification import FacebookListingClassification
from ticket_tracker.db.models.pipeline_tables import PipelineRun
from ticket_tracker.pipeline.stage2_classify.gemini import classify_batch

BATCH_SIZE = 15

_COUNT_ALL = text("""
    SELECT COUNT(*) FROM facebook_listing_raw
    WHERE valid_to IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM facebook_listing_classifications
          WHERE raw_listing_id = facebook_listing_raw.id
      )
""")

_COUNT_EVENT = text("""
    SELECT COUNT(*) FROM facebook_listing_raw
    WHERE valid_to IS NULL
      AND event_id = :event_id
      AND NOT EXISTS (
          SELECT 1 FROM facebook_listing_classifications
          WHERE raw_listing_id = facebook_listing_raw.id
      )
""")

_FETCH_ALL = text("""
    SELECT id, title, description, price FROM facebook_listing_raw
    WHERE valid_to IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM facebook_listing_classifications
          WHERE raw_listing_id = facebook_listing_raw.id
      )
    ORDER BY id
    LIMIT :limit OFFSET :offset
""")

_FETCH_EVENT = text("""
    SELECT id, title, description, price FROM facebook_listing_raw
    WHERE valid_to IS NULL
      AND event_id = :event_id
      AND NOT EXISTS (
          SELECT 1 FROM facebook_listing_classifications
          WHERE raw_listing_id = facebook_listing_raw.id
      )
    ORDER BY id
    LIMIT :limit OFFSET :offset
""")


@dataclass
class ClassifyResult:
    run_id: uuid.UUID
    status: str
    total: int = 0
    classified: int = 0
    errors: int = 0


def run(event_id: Optional[uuid.UUID] = None, event_key: Optional[str] = None) -> ClassifyResult:
    """Classify all unclassified current-version raw listings via Gemini.

    Pass event_id to restrict to one event, or omit to classify across all events.
    event_key is used as a human-readable source label in the pipeline_runs record.
    Idempotent: records already in facebook_listing_classifications are skipped via NOT EXISTS.
    Failed batches are logged and retried on the next run.
    """
    with SessionLocal() as session:
        db_run = _create_run(session, event_key)
        result = ClassifyResult(run_id=db_run.id, status="completed")

        if event_id:
            total = session.execute(_COUNT_EVENT, {"event_id": str(event_id)}).scalar() or 0
        else:
            total = session.execute(_COUNT_ALL).scalar() or 0

        result.total = total

        if total == 0:
            logger.info("[Classify] No unclassified listings — nothing to do")
            _finish_run(session, db_run, result)
            return result

        logger.info(f"[Classify] {total} listings to classify in batches of {BATCH_SIZE}")

        offset = 0
        while offset < total:
            fetch_params: dict = {"limit": BATCH_SIZE, "offset": offset}
            if event_id:
                fetch_params["event_id"] = str(event_id)
                rows = session.execute(_FETCH_EVENT, fetch_params).fetchall()
            else:
                rows = session.execute(_FETCH_ALL, fetch_params).fetchall()

            if not rows:
                break

            listings = [
                {
                    "id": row.id,
                    "title": row.title,
                    "description": row.description,
                    "price": float(row.price) if row.price is not None else None,
                }
                for row in rows
            ]

            try:
                classifications = classify_batch(listings)
                for row, clf in zip(rows, classifications):
                    session.add(FacebookListingClassification(
                        raw_listing_id=row.id,
                        llm_model="gemini-3.1-flash-lite",
                        is_ticket=bool(clf.get("is_ticket", False)),
                        is_buyer_listing=bool(clf.get("is_buyer_listing", False)),
                        is_merch=bool(clf.get("is_merch", False)),
                        is_wrong_category=bool(clf.get("is_wrong_category", False)),
                        extracted_event=clf.get("extracted_event"),
                        extracted_price=clf.get("extracted_price"),
                        face_value_price=clf.get("face_value_price"),
                        face_value_mentioned=bool(clf.get("face_value_mentioned", False)),
                        quantity=clf.get("quantity"),
                        ticket_type=clf.get("ticket_type"),
                        event_days=clf.get("event_days"),
                        price_negotiable=bool(clf.get("price_negotiable", False)),
                        includes_extras=clf.get("includes_extras"),
                        seller_note=clf.get("seller_note"),
                        confidence=clf.get("confidence", "low"),
                        reason=clf.get("reason"),
                        raw_llm_response=clf,
                    ))
                session.commit()
                result.classified += len(rows)
                logger.info(f"[Classify] {result.classified}/{total} classified")

            except Exception as exc:
                logger.error(f"[Classify] Batch at offset {offset} failed: {exc}")
                result.errors += len(rows)
                session.rollback()

            offset += BATCH_SIZE

        result.status = "completed" if result.errors == 0 else "partial"
        _finish_run(session, db_run, result)

    logger.info(
        f"[Classify] Done — total={result.total} "
        f"classified={result.classified} errors={result.errors}"
    )
    return result


def _create_run(session: Session, event_key: Optional[str]) -> PipelineRun:
    run = PipelineRun(
        stage="stage2",
        source=event_key if event_key else "all",
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finish_run(session: Session, run: PipelineRun, result: ClassifyResult) -> None:
    run.status = result.status
    run.finished_at = datetime.now(timezone.utc)
    run.total_records = result.total
    run.newly_added_count = result.classified
    run.error_count = result.errors
    session.commit()
