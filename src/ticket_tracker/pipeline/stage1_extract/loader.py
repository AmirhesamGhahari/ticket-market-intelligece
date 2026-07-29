"""Upserts validated Apify records into veld_2026_raw.

Upsert behaviour on UNIQUE conflict (listing_url):
  - UPDATE: last_seen_at, updated_at, is_sold, final_price, image_urls,
            pipeline_run_id (most recent run that saw this listing).
  - PRESERVE: first_seen_at — never overwritten. This protects the
              historical timeline which is the core data asset.

Records are written in batches for performance. Each batch is committed
in its own transaction so a batch failure does not roll back prior work.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

_UPSERT_SQL = text("""
INSERT INTO veld_2026_raw (
    pipeline_run_id,
    fb_listing_id,
    listing_url,
    seller_profile_id,
    title,
    description,
    initial_price,
    final_price,
    currency,
    condition,
    location_raw,
    image_urls,
    is_sold,
    listed_at,
    scraped_at,
    search_keyword,
    search_city,
    raw_payload,
    first_seen_at,
    last_seen_at
)
VALUES (
    :pipeline_run_id,
    :fb_listing_id,
    :listing_url,
    :seller_profile_id,
    :title,
    :description,
    :initial_price,
    :final_price,
    :currency,
    :condition,
    :location_raw,
    :image_urls::jsonb,
    :is_sold,
    :listed_at,
    :scraped_at,
    :search_keyword,
    :search_city,
    :raw_payload::jsonb,
    now(),
    now()
)
ON CONFLICT (listing_url) DO UPDATE SET
    pipeline_run_id   = EXCLUDED.pipeline_run_id,
    final_price       = EXCLUDED.final_price,
    is_sold           = EXCLUDED.is_sold,
    image_urls        = EXCLUDED.image_urls,
    last_seen_at      = now(),
    updated_at        = now()
""")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _build_params(record: dict[str, Any], run_id: uuid.UUID) -> dict[str, Any]:
    import json

    discovery = record.get("discovery_input") or {}
    image_urls = record.get("images") or []

    # Build a clean payload to store — cookies already stripped by reader.
    safe_payload = {k: v for k, v in record.items() if k not in ("input",)}

    return {
        "pipeline_run_id": str(run_id),
        "fb_listing_id": str(record.get("product_id", "")),
        "listing_url": record["url"],
        "seller_profile_id": record.get("profile_id"),
        "title": record.get("title"),
        "description": record.get("description"),
        "initial_price": _to_decimal(record.get("initial_price")),
        "final_price": _to_decimal(record.get("final_price")),
        "currency": record.get("currency", "CAD"),
        "condition": record.get("condition"),
        "location_raw": record.get("location"),
        "image_urls": json.dumps(image_urls),
        "is_sold": bool(record.get("is_sold", False)),
        "listed_at": _parse_datetime(record.get("listing_date")),
        "scraped_at": _parse_datetime(record.get("timestamp")),
        "search_keyword": discovery.get("keyword"),
        "search_city": discovery.get("city"),
        "raw_payload": json.dumps(safe_payload),
    }


def upsert_batch(
    session: Session,
    records: list[dict[str, Any]],
    run_id: uuid.UUID,
) -> int:
    """Upsert a batch of validated records. Returns the count of rows affected."""
    if not records:
        return 0

    params = [_build_params(r, run_id) for r in records]
    result = session.execute(_UPSERT_SQL, params)
    session.commit()

    rows = result.rowcount
    logger.debug(f"Upserted batch of {len(records)} records ({rows} rows affected)")
    return len(records)
