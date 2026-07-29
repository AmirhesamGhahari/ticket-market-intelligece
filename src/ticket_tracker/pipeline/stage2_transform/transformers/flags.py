"""Classify listings into types and determine relevance.

listing_type values (evaluated in order, first match wins):
  "irrelevant" — title does not mention the target keyword ("veld")
  "promoter"   — official promoter or spam listing
  "wanted"     — buyer looking for tickets (not selling)
  "resale"     — genuine resale listing (default)
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import NamedTuple

_PROMOTER_TITLE_RE = re.compile(
    r"\b(?:official\s+)?(?:ink\s+)?promoter\b",
    re.IGNORECASE,
)
_PROMOTER_DESC_RE = re.compile(
    r"\b(?:official\s+)?(?:ink\s+)?promoter\b",
    re.IGNORECASE,
)
_WANTED_RE = re.compile(
    r"\b(?:looking\s+for|wtb|want\s+to\s+buy|need\s+tickets?|iso\b|in\s+search\s+of)\b",
    re.IGNORECASE,
)


class FlagResult(NamedTuple):
    listing_type: str
    is_relevant: bool


def transform(
    title: str | None,
    description: str | None,
    price: Decimal | None,
    search_keyword: str | None = "veld",
) -> FlagResult:
    """Determine the listing_type and is_relevant flag."""
    title_lower = (title or "").lower()
    desc_lower = (description or "").lower()
    keyword = (search_keyword or "veld").lower()

    # Relevance: title must mention the target event keyword.
    is_relevant = keyword in title_lower
    if not is_relevant:
        return FlagResult(listing_type="irrelevant", is_relevant=False)

    # Promoter: price == $1 OR promoter language in title or description.
    is_promoter = (
        (price is not None and price <= Decimal("1.0"))
        or bool(_PROMOTER_TITLE_RE.search(title or ""))
        or bool(_PROMOTER_DESC_RE.search(description or ""))
    )
    if is_promoter:
        return FlagResult(listing_type="promoter", is_relevant=True)

    # Wanted: buyer looking for tickets.
    is_wanted = bool(_WANTED_RE.search(title or "")) or bool(
        _WANTED_RE.search(description or "")
    )
    if is_wanted:
        return FlagResult(listing_type="wanted", is_relevant=True)

    return FlagResult(listing_type="resale", is_relevant=True)
