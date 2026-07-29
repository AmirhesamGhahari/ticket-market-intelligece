"""Reads raw records from veld_2026_raw that have not yet been transformed.

Uses a LEFT JOIN to find rows in veld_2026_raw with no matching row in
veld_2026_transformed. This means re-running stage 2 on the same data
is safe — already-transformed records are silently skipped.
"""

from __future__ import annotations

from typing import Generator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

_UNTRANSFORMED_SQL = text("""
    SELECT
        r.id,
        r.pipeline_run_id,
        r.fb_listing_id,
        r.listing_url,
        r.seller_profile_id,
        r.title,
        r.description,
        r.initial_price,
        r.final_price,
        r.currency,
        r.condition,
        r.location_raw,
        r.image_urls,
        r.is_sold,
        r.listed_at,
        r.scraped_at,
        r.search_keyword,
        r.search_city
    FROM veld_2026_raw r
    LEFT JOIN veld_2026_transformed t ON t.raw_id = r.id
    WHERE t.id IS NULL
    ORDER BY r.id
""")


def iter_untransformed(
    session: Session, batch_size: int = 100
) -> Generator[list[dict], None, None]:
    """Yield batches of raw rows that have not yet been transformed.

    Each item in a batch is a plain dict keyed by column name.
    Batching avoids loading the full dataset into memory.
    """
    result = session.execute(_UNTRANSFORMED_SQL)
    keys = result.keys()

    batch: list[dict] = []
    total = 0

    for row in result:
        batch.append(dict(zip(keys, row)))
        total += 1
        if len(batch) >= batch_size:
            logger.debug(f"Yielding batch of {len(batch)} raw rows (total so far: {total})")
            yield batch
            batch = []

    if batch:
        logger.debug(f"Yielding final batch of {len(batch)} raw rows (total: {total})")
        yield batch

    logger.info(f"Stage 2 reader: {total} untransformed raw records found")
