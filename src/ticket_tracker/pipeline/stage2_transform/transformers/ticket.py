"""Extract ticket intelligence from listing titles.

All extraction is regex-based. Rules are applied in priority order;
the first match wins for fields like quantity and ticket_type.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ── Quantity ──────────────────────────────────────────────────────────────────

_QUANTITY_PATTERNS: list[tuple[re.Pattern, int | None]] = [
    # Explicit multiplier: "2x", "3X", etc.
    (re.compile(r"\b(\d+)\s*x\b", re.IGNORECASE), None),
    # "2 tickets", "3 passes", "4 wristbands", "2 bracelets"
    (re.compile(r"\b(\d+)\s*(?:tickets?|passes?|wristbands?|bracelets?)\b", re.IGNORECASE), None),
    # "a pair" or "pair"
    (re.compile(r"\bpair\b", re.IGNORECASE), 2),
    # "2 day" / "saturday and sunday" → still 1 ticket covering multiple days
    # (handled separately — doesn't affect quantity)
]


def extract_quantity(title: str | None) -> int:
    if not title:
        return 1
    for pattern, fixed_value in _QUANTITY_PATTERNS:
        match = pattern.search(title)
        if match:
            if fixed_value is not None:
                return fixed_value
            try:
                return int(match.group(1))
            except (IndexError, ValueError):
                continue
    return 1


# ── Ticket Type ───────────────────────────────────────────────────────────────

_VIP_RE = re.compile(r"\bvip\b", re.IGNORECASE)
_GA_RE = re.compile(r"\b(?:ga|general\s+admission)\b", re.IGNORECASE)


def extract_ticket_type(title: str | None) -> tuple[str, str | None]:
    """Return (ticket_type, ticket_type_raw) where ticket_type_raw is the
    matched phrase for audit purposes."""
    if not title:
        return "UNKNOWN", None

    vip_match = _VIP_RE.search(title)
    if vip_match:
        return "VIP", vip_match.group(0)

    ga_match = _GA_RE.search(title)
    if ga_match:
        return "GA", ga_match.group(0)

    return "UNKNOWN", None


# ── Event Days ────────────────────────────────────────────────────────────────

_THREE_DAY_RE = re.compile(
    r"\b(?:3[\s\-]day|three[\s\-]day|full\s+weekend|all\s+3\s+days?)\b",
    re.IGNORECASE,
)
_FRIDAY_RE = re.compile(r"\b(?:friday|fri)\b", re.IGNORECASE)
_SATURDAY_RE = re.compile(r"\b(?:saturday|sat)\b", re.IGNORECASE)
_SUNDAY_RE = re.compile(r"\b(?:sunday|sun)\b", re.IGNORECASE)


def extract_event_days(title: str | None) -> list[str]:
    """Return a list of day names mentioned in the title."""
    if not title:
        return []

    if _THREE_DAY_RE.search(title):
        return ["Friday", "Saturday", "Sunday"]

    days: list[str] = []
    if _FRIDAY_RE.search(title):
        days.append("Friday")
    if _SATURDAY_RE.search(title):
        days.append("Saturday")
    if _SUNDAY_RE.search(title):
        days.append("Sunday")

    return days


# ── Combined ──────────────────────────────────────────────────────────────────

class TicketResult(NamedTuple):
    quantity: int
    ticket_type: str
    ticket_type_raw: str | None
    event_days: list[str]


def transform(title: str | None) -> TicketResult:
    quantity = extract_quantity(title)
    ticket_type, ticket_type_raw = extract_ticket_type(title)
    event_days = extract_event_days(title)
    return TicketResult(
        quantity=quantity,
        ticket_type=ticket_type,
        ticket_type_raw=ticket_type_raw,
        event_days=event_days,
    )
