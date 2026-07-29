"""Reads an Apify JSON output file and yields individual raw record dicts.

Responsibilities:
  - Open and parse the top-level JSON array.
  - Detect Apify-level error records (records containing an "error" field).
  - Yield each record as a plain dict; caller decides what to do with it.
  - Strip the "input" field (contains sensitive Facebook session cookies)
    before any further processing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

from loguru import logger

from ticket_tracker.pipeline.errors import ErrorCode, PipelineError


def _strip_sensitive_fields(record: dict) -> dict:
    """Remove fields that must never be stored (session cookies, etc.)."""
    record.pop("input", None)
    return record


def load_records(
    file_path: Path,
) -> Generator[tuple[dict, PipelineError | None], None, None]:
    """Yield (record, error) tuples from an Apify JSON file.

    Yields:
        (record, None)        — a usable record, cookies already stripped.
        (raw_record, error)   — a record that failed at the read level;
                                caller should log the error and skip.

    The caller is responsible for all further validation and DB writes.
    Apify error records (those with an "error" key) are yielded with a
    PipelineError so the caller can count and log them accurately.
    """
    logger.info(f"Opening source file: {file_path}")

    try:
        with open(file_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise PipelineError(
            ErrorCode.JSON_DECODE_ERROR,
            f"Top-level JSON decode failed: {exc}",
        ) from exc

    if not isinstance(data, list):
        raise PipelineError(
            ErrorCode.JSON_DECODE_ERROR,
            f"Expected a JSON array at the top level, got {type(data).__name__}",
        )

    logger.info(f"Loaded {len(data)} records from file")

    for raw in data:
        if not isinstance(raw, dict):
            yield {}, PipelineError(
                ErrorCode.JSON_DECODE_ERROR,
                f"Record is not a dict: {type(raw).__name__}",
                raw_data={},
            )
            continue

        # Apify writes its own error records with an "error" key.
        if "error" in raw:
            apify_code = raw.get("error_code", "unknown")
            # Extract URL before stripping — input field holds it on error records.
            url = (raw.get("input") or {}).get("url", "unknown") if isinstance(raw.get("input"), dict) else "unknown"
            stripped = _strip_sensitive_fields(dict(raw))
            yield stripped, PipelineError(
                ErrorCode.APIFY_ERROR,
                f"Apify error '{apify_code}' for URL: {url}",
                raw_data=stripped,
                source_identifier=url,
            )
            continue

        # Strip cookies and other sensitive fields before returning.
        record = _strip_sensitive_fields(dict(raw))
        yield record, None
