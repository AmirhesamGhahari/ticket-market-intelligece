"""Inserts transformed records into veld_2026_transformed.

Uses INSERT ... ON CONFLICT (raw_id) DO NOTHING so that re-running
stage 2 on already-transformed data is idempotent and silent.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

_INSERT_SQL = text("""
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
    search_keyword,
    image_urls,
    condition,
    initial_price,
    price,
    price_per_unit,
    price_drop,
    price_drop_pct,
    price_is_anomaly,
    location_raw,
    location_city,
    location_province,
    location_region,
    quantity,
    ticket_type,
    ticket_type_raw,
    event_days,
    listing_type,
    is_relevant
)
VALUES (
    :raw_id,
    :pipeline_run_id,
    :fb_listing_id,
    :listing_url,
    :seller_profile_id,
    :title,
    :description,
    :currency,
    :is_sold,
    :listed_at,
    :scraped_at,
    :search_keyword,
    :image_urls::jsonb,
    :condition,
    :initial_price,
    :price,
    :price_per_unit,
    :price_drop,
    :price_drop_pct,
    :price_is_anomaly,
    :location_raw,
    :location_city,
    :location_province,
    :location_region,
    :quantity,
    :ticket_type,
    :ticket_type_raw,
    :event_days::jsonb,
    :listing_type,
    :is_relevant
)
ON CONFLICT (raw_id) DO NOTHING
""")


def _build_params(record: dict[str, Any], run_id: uuid.UUID) -> dict[str, Any]:
    return {
        "raw_id": record["raw_id"],
        "pipeline_run_id": str(run_id),
        "fb_listing_id": record["fb_listing_id"],
        "listing_url": record["listing_url"],
        "seller_profile_id": record.get("seller_profile_id"),
        "title": record.get("title"),
        "description": record.get("description"),
        "currency": record.get("currency", "CAD"),
        "is_sold": record.get("is_sold", False),
        "listed_at": record.get("listed_at"),
        "scraped_at": record.get("scraped_at"),
        "search_keyword": record.get("search_keyword"),
        "image_urls": json.dumps(record.get("image_urls") or []),
        "condition": record.get("condition"),
        "initial_price": record.get("initial_price"),
        "price": record.get("price"),
        "price_per_unit": record.get("price_per_unit"),
        "price_drop": record.get("price_drop"),
        "price_drop_pct": record.get("price_drop_pct"),
        "price_is_anomaly": record.get("price_is_anomaly", False),
        "location_raw": record.get("location_raw"),
        "location_city": record.get("location_city"),
        "location_province": record.get("location_province"),
        "location_region": record.get("location_region"),
        "quantity": record.get("quantity", 1),
        "ticket_type": record.get("ticket_type", "UNKNOWN"),
        "ticket_type_raw": record.get("ticket_type_raw"),
        "event_days": json.dumps(record.get("event_days") or []),
        "listing_type": record.get("listing_type", "resale"),
        "is_relevant": record.get("is_relevant", True),
    }


def insert_batch(
    session: Session,
    records: list[dict[str, Any]],
    run_id: uuid.UUID,
) -> int:
    """Insert a batch of transformed records. Returns count inserted."""
    if not records:
        return 0

    params = [_build_params(r, run_id) for r in records]
    session.execute(_INSERT_SQL, params)
    session.commit()

    logger.debug(f"Inserted batch of {len(records)} transformed records")
    return len(records)
