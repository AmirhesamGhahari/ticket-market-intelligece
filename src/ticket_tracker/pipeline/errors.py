from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # ── Stage 1: Extract & Load ──────────────────────────────────────────────
    APIFY_ERROR = "APIFY_ERROR"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_URL = "INVALID_URL"
    DUPLICATE_SAME_RUN = "DUPLICATE_SAME_RUN"
    JSON_DECODE_ERROR = "JSON_DECODE_ERROR"

    # ── Stage 2: Transform & Load ────────────────────────────────────────────
    PRICE_PARSE_ERROR = "PRICE_PARSE_ERROR"
    LOCATION_PARSE_ERROR = "LOCATION_PARSE_ERROR"
    DATE_PARSE_ERROR = "DATE_PARSE_ERROR"
    PRICE_RANGE_ANOMALY = "PRICE_RANGE_ANOMALY"
    TRANSFORM_FAILED = "TRANSFORM_FAILED"


class PipelineError(Exception):
    """Raised when a single record cannot be processed."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        raw_data: dict[str, Any] | None = None,
        source_identifier: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.raw_data = raw_data or {}
        self.source_identifier = source_identifier
