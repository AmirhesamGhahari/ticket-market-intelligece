"""Validates the output of the transformation step before writing to the DB.

This is a lightweight sanity check. It runs after all transformers have
produced their results and before the loader writes to veld_2026_transformed.

We validate that:
  - fb_listing_id is present.
  - listing_url is present.
  - listing_type is one of the known values.
"""

from __future__ import annotations

from typing import Any

from ticket_tracker.pipeline.errors import ErrorCode, PipelineError

_VALID_LISTING_TYPES = frozenset({"resale", "promoter", "wanted", "irrelevant"})


def validate(record: dict[str, Any]) -> dict[str, Any]:
    """Validate a transformed record dict.

    Returns the record unchanged if valid.
    Raises PipelineError if critically broken.
    """
    if not record.get("fb_listing_id"):
        raise PipelineError(
            ErrorCode.TRANSFORM_FAILED,
            "Transformed record is missing fb_listing_id",
            source_identifier=record.get("listing_url"),
        )

    if not record.get("listing_url"):
        raise PipelineError(
            ErrorCode.TRANSFORM_FAILED,
            "Transformed record is missing listing_url",
            source_identifier=record.get("fb_listing_id"),
        )

    if record.get("listing_type") not in _VALID_LISTING_TYPES:
        raise PipelineError(
            ErrorCode.TRANSFORM_FAILED,
            f"Unknown listing_type: {record.get('listing_type')!r}",
            source_identifier=record.get("listing_url"),
        )

    return record
