"""Stage 2 transform pipeline.

Reads from veld_2026_raw_extract and loads into veld_2026_transformed
via a single INSERT SELECT statement — all transformation logic lives in SQL.

Incremental by design: the WHERE clause skips raw records that already have
a corresponding row in transformed, so re-runs are always safe.

Transformations applied in SQL:
  - quantity    : extract "Nx" pattern from title (e.g. "2x tickets" → 2)
  - ticket_type : VIP or GA detected from title keywords, else UNKNOWN
  - event_days  : Friday / Saturday / Sunday detected from title as a JSONB array
  - price_per_unit : price / quantity
  - price_is_anomaly : outside the $50–$2000 reasonable range
  - is_relevant : title contains the word "veld"
  - listing_type : always "resale" for Facebook Marketplace
  - currency     : always "CAD"
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

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
    success: int = 0
    errors: int = 0


# ── SQL ───────────────────────────────────────────────────────────────────────


_COUNT_PENDING_SQL = text("""
    SELECT COUNT(*)
    FROM veld_2026_raw_extract
    WHERE id NOT IN (SELECT raw_id FROM veld_2026_transformed)
""")

_TRANSFORM_SQL = text("""
    WITH source AS (
        SELECT
            r.id,
            r.fb_listing_id,
            r.listing_url,
            r.seller_profile_id,
            r.title,
            r.description,
            r.price,
            r.location_city,
            r.location_state,
            r.image_urls,
            r.is_sold,
            r.listed_at,
            r.scraped_at,
            -- Quantity: look for "Nx" pattern (e.g. "2x VELD VIP")
            COALESCE(
                (regexp_match(r.title, '(\d+)[[:space:]]*[xX][[:space:]]', 'i'))[1]::int,
                1
            ) AS quantity
        FROM veld_2026_raw_extract r
        WHERE r.id NOT IN (SELECT raw_id FROM veld_2026_transformed)
    )
    INSERT INTO veld_2026_transformed (
        raw_id,
        pipeline_run_id,
        fb_listing_id,
        listing_url,
        seller_profile_id,
        title,
        description,
        currency,
        is_sold,
        listed_at,
        scraped_at,
        image_urls,
        price,
        price_per_unit,
        price_is_anomaly,
        location_city,
        location_state,
        quantity,
        ticket_type,
        event_days,
        listing_type,
        is_relevant
    )
    SELECT
        s.id                                                    AS raw_id,
        :run_id                                                 AS pipeline_run_id,
        s.fb_listing_id,
        s.listing_url,
        s.seller_profile_id,
        s.title,
        s.description,
        'CAD'                                                   AS currency,
        s.is_sold,
        s.listed_at,
        s.scraped_at,
        s.image_urls,
        s.price,

        -- price_per_unit: price divided by quantity
        s.price / NULLIF(s.quantity, 0)                         AS price_per_unit,

        -- price_is_anomaly: flag listings outside the $50–$2000 range
        CASE
            WHEN s.price IS NULL      THEN false
            WHEN s.price < 50         THEN true
            WHEN s.price > 2000       THEN true
            ELSE false
        END                                                     AS price_is_anomaly,

        s.location_city,
        s.location_state,
        s.quantity,

        -- ticket_type: VIP takes priority, then GA, then UNKNOWN
        CASE
            WHEN s.title ~* '\mvip\M'                           THEN 'VIP'
            WHEN s.title ~* '\mga\M'                            THEN 'GA'
            ELSE 'UNKNOWN'
        END                                                     AS ticket_type,

        -- event_days: which festival days are mentioned in the title
        NULLIF(
            to_jsonb(
                array_remove(ARRAY[
                    CASE WHEN s.title ~* '\m(fri(day)?|day[[:space:]]*1)\M'
                         THEN 'Friday'  END,
                    CASE WHEN s.title ~* '\m(sat(urday)?|day[[:space:]]*2)\M'
                         THEN 'Saturday' END,
                    CASE WHEN s.title ~* '\m(sun(day)?|day[[:space:]]*3)\M'
                         THEN 'Sunday'  END
                ], NULL)
            ),
            '[]'::jsonb
        )                                                       AS event_days,

        'resale'                                                AS listing_type,

        -- is_relevant: title contains the word "veld"
        (s.title ~* '\mveld\M')                                 AS is_relevant

    FROM source s
    ON CONFLICT (raw_id) DO NOTHING
""")


# ── Pipeline run helpers ──────────────────────────────────────────────────────


def _create_run(session: Session) -> PipelineRun:
    run = PipelineRun(stage="stage2", source=None, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finish_run(session: Session, run: PipelineRun, result: PipelineResult) -> None:
    run.status = result.status
    run.finished_at = datetime.now(timezone.utc)
    run.total_records = result.total
    run.success_count = result.success
    run.error_count = result.errors
    session.commit()


# ── Entry point ───────────────────────────────────────────────────────────────


def run() -> PipelineResult:
    """Run Stage 2: transform all untransformed raw records into veld_2026_transformed.

    Steps:
      1. Create pipeline_run record (status="running").
      2. Count raw records not yet in transformed — exit early if none.
      3. Execute single INSERT SELECT with all transformation logic in SQL.
      4. Finalize pipeline_run with row counts.
    """
    logger.info("[Stage 2] Starting")

    with SessionLocal() as session:
        db_run = _create_run(session)
        result = PipelineResult(run_id=db_run.id, status="completed")

        # Step 2 — check for pending work
        pending = session.execute(_COUNT_PENDING_SQL).scalar() or 0
        result.total = pending

        if pending == 0:
            logger.info("[Stage 2] No new raw records to transform — nothing to do")
            _finish_run(session, db_run, result)
            return result

        logger.info(f"[Stage 2] {pending} raw records to transform")

        # Step 3 — transform everything in one SQL statement
        db_result = session.execute(_TRANSFORM_SQL, {"run_id": str(db_run.id)})
        session.commit()

        result.success = db_result.rowcount
        result.errors = pending - result.success

        # Step 4 — finalize run record
        _finish_run(session, db_run, result)

    logger.info(
        f"[Stage 2] Done — total={result.total} "
        f"success={result.success} errors={result.errors}"
    )
    return result
