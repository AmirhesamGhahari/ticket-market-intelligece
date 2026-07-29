"""Validates a raw Apify record before writing to veld_2026_raw.

Validation at this stage is intentionally minimal — we want to preserve
as much data as possible in the raw table. We only reject records that are
structurally broken and cannot be meaningfully stored.

Rules:
  - url must be present and non-empty (it is our dedup key).
  - product_id must be present and non-empty.
  - final_price must be present (can be 0 — anomaly flagging is Stage 2's job).
  - url must match the expected Facebook Marketplace pattern.
"""

from __future__ import annotations

import re
from typing import Any

from ticket_tracker.pipeline.errors import ErrorCode, PipelineError

_FB_MARKETPLACE_URL_RE = re.compile(
    r"https://www\.facebook\.com/marketplace/item/\d+",
    re.IGNORECASE,
)

_REQUIRED_FIELDS: list[str] = ["url", "product_id", "final_price"]


def validate(record: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw Apify record.

    Returns the record unchanged if valid.
    Raises PipelineError if the record fails validation.
    """
    # Check required fields exist and are not None / empty string.
    for field in _REQUIRED_FIELDS:
        value = record.get(field)
        if value is None or value == "":
            raise PipelineError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                f"Required field '{field}' is missing or null",
                raw_data=record,
                source_identifier=record.get("url") or record.get("product_id"),
            )

    # Validate URL pattern.
    url: str = record["url"]
    if not _FB_MARKETPLACE_URL_RE.match(url):
        raise PipelineError(
            ErrorCode.INVALID_URL,
            f"URL does not match expected Facebook Marketplace pattern: {url!r}",
            raw_data=record,
            source_identifier=url,
        )

    return record
