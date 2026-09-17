"""Gemini classifier — prompt definitions and API client combined."""

from __future__ import annotations

import json
import time

from google import genai
from google.genai import types
from loguru import logger

from ticket_tracker.config import settings

_MODEL_NAME = "gemini-3.1-flash-lite"
_RATE_LIMIT_SLEEP = 8.0

# ── System instruction ─────────────────────────────────────────────────────────
# Passed as system_instruction to Gemini — separated from listing data so the
# model treats it as standing context rather than part of the conversation turn.

_SYSTEM_INSTRUCTION = """\
Classify Facebook Marketplace listings scraped from Canadian cities using \
event-related keywords. Events span ANY genre/type of live music in Canada \
(festivals, concerts, tours, club nights) — not just one genre. For each listing \
decide: ticket sale, buyer/wanted, merch, wrong category, or unknown.

Sellers post an asking price; buyers post wanted/ISO ads. Price alone (including \
$0/$1) does NOT distinguish buyer from seller — sellers often list $0/$1 to attract \
interest. French (Quebec): "vends/je vends"=selling, "cherche/recherche/ISO"=looking \
for, "billets"=tickets, "place"=spot, "passe"=pass.

CATEGORIES
- is_ticket=true: selling admission. Signals: "selling"/"for sale"/"vends", \
quantity ("2x"), tier (VIP/GA), event days. MINIMAL LISTING RULE: a title that's \
solely/mainly a known event or artist name (e.g. "VELD 2026", "Rufus Du Sol Tix", \
"Rufus Du Sol x4 sec136") with little/no description, no buyer signals, no merch \
signals → is_ticket=true, confidence="high", regardless of price ($0/$1 here is a \
seller lowball, not a buyer signal).
- is_buyer_listing=true (is_ticket=false): ONLY explicit request language — \
"ISO"/"WTB"/"looking for"/"need tickets"/"wanted"/"cherche"/"recherche". Never \
infer buyer status from price alone.
- is_merch=true: non-admission physical items — clothing, festival outfits, \
posters, albums, glow sticks, wristbands, lanyards. Festival clothing is merch \
even with an event name in the title.
- is_wrong_category=true: unrelated items, coincidental keyword match (appliances, \
pest repellers, electronics, furniture, tools, vehicles).
- Unknown: all flags false.

FIELDS
extracted_event: event/artist/tour name if identifiable, else null.
extracted_price: price PER TICKET (2 tickets for $800 total → 400.0; "each" \
overrides a total-looking price). null if buyer listing or price is $0/$1 \
(placeholder — even when is_ticket=true via the minimal listing rule).
face_value_price: only if seller explicitly states original price ("paid $X"/"face \
value $X"), else null. face_value_mentioned: true if any face value is mentioned \
even without a clear number.
quantity: integer count ("2x"/"a pair"→2); null if not mentioned.
ticket_type: "VIP"|"GA"|"WEEKEND_PASS"|"DAY_PASS"|"UNKNOWN"; null only if clearly \
not a ticket.
event_days: specific day(s) for multi-day events, e.g. ["Saturday"]; null if \
single-day, unspecified, or a plain "weekend pass".
price_negotiable: true for "OBO"/"negotiable"/"flexible"/"make an offer".
includes_extras: any of "parking_pass","camping_pass","shuttle","hotel", \
"meet_and_greet","locker","fast_lane","wristband_included"; else null.
seller_note: one short sentence on notable logistics/urgency/condition, else null.
confidence: "high" (clear), "medium" (likely, one signal missing/contradictory), \
"low" (ambiguous).
reason: one sentence explaining the verdict.

OUTPUT: a JSON ARRAY, one object per listing, same order as input, ALL fields \
present (null for unknown/inapplicable; booleans never null):
[{"is_ticket":bool,"is_buyer_listing":bool,"is_merch":bool,"is_wrong_category":bool,
"extracted_event":str|null,"extracted_price":num|null,"face_value_price":num|null,
"face_value_mentioned":bool,"quantity":int|null,
"ticket_type":"VIP"|"GA"|"WEEKEND_PASS"|"DAY_PASS"|"UNKNOWN"|null,
"event_days":[str]|null,"price_negotiable":bool,"includes_extras":[str]|null,
"seller_note":str|null,"confidence":"high"|"medium"|"low","reason":str}, ...]

EXAMPLES
"Rufus Du Sol Tix" | 0 | "" → is_ticket=true, extracted_event="Rufus Du Sol", \
extracted_price=null, ticket_type="UNKNOWN", confidence="high", reason="Bare \
artist-name listing; $0 is a lowball, not a buyer signal."
"2x VELD VIP Saturday $400 each OBO" | 800 | "Selling 2 VIP Saturday tickets to \
VELD 2026. Paid $350 face value each." → is_ticket=true, extracted_event="VELD", \
extracted_price=400.0, face_value_price=350.0, face_value_mentioned=true, \
quantity=2, ticket_type="VIP", event_days=["Saturday"], price_negotiable=true, \
confidence="high", reason="Selling 2 VIP tickets with face value and OBO noted."
"Recherche 2 billets Electric Island" | 1 | "Cherche 2 billets pour Electric \
Island dimanche." → is_ticket=false, is_buyer_listing=true, \
extracted_event="Electric Island", quantity=2, event_days=["Sunday"], \
confidence="high", reason="Explicit buyer language ('cherche billets')."
"VELD 2026 crop top rave outfit" | 45 | "Brand new, never worn." → is_merch=true, \
confidence="high", reason="Festival clothing, not a ticket."
"""


# ── Listing block builder ─────────────────────────────────────────────────────

def _build_listing_block(listings: list[dict]) -> str:
    lines = ["Classify the following Facebook Marketplace listings:\n"]
    for i, listing in enumerate(listings, 1):
        lines.append(f"[{i}]")
        lines.append(f"  title: {listing.get('title') or 'N/A'}")
        price = listing.get("price")
        lines.append(f"  price: {price if price is not None else 'N/A'}")
        desc = (listing.get("description") or "").strip()
        if desc:
            lines.append(f"  description: {desc[:500]}")
        lines.append("")
    return "\n".join(lines)


# ── API client ────────────────────────────────────────────────────────────────

def classify_batch(listings: list[dict]) -> list[dict]:
    """Send a batch of listings to Gemini and return one classification dict per listing.

    Raises ValueError if the response count doesn't match input or JSON is malformed.
    Caller catches and handles errors per batch — failed batches are retried on next run.
    """
    client = genai.Client(api_key=settings.gemini_api_key)

    response = client.models.generate_content(
        model=_MODEL_NAME,
        contents=_build_listing_block(listings),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )

    results: list[dict] = json.loads(response.text)

    if not isinstance(results, list):
        raise ValueError(f"Gemini returned non-list response: {type(results)}")

    if len(results) != len(listings):
        raise ValueError(
            f"Gemini returned {len(results)} results for {len(listings)} listings"
        )

    time.sleep(_RATE_LIMIT_SLEEP)
    return results
