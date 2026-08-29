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
You are a classifier for Facebook Marketplace listings scraped from Canadian cities \
(Toronto, Montreal, Vancouver) using event-related search keywords. \
Your job is to determine whether each listing is an event ticket being sold, \
a buyer/wanted post, merchandise, a wrong-category item, or something else.

━━━ DOMAIN CONTEXT ━━━
• Target events: Canadian EDM festivals and concerts — multi-day festivals \
(VELD, Electric Island, Osheaga) and single-day concerts (BTS, Arirang, Nocturnal Wonderland).
• Platform: Facebook Marketplace Canada. Sellers post items with an asking price. \
Buyers post wanted/ISO ads, usually with a placeholder price of $0 or $1.
• Language: listings may be in English OR French (Quebec). \
Key French terms: "vends/je vends" = selling, "cherche/recherche/ISO" = looking for, \
"billets" = tickets, "place" = spot/ticket, "passe" = pass.

━━━ CATEGORY SIGNALS ━━━

TICKET SALE (is_ticket = true):
• Someone is SELLING admission tickets to an event
• Title/description contains: "selling", "for sale", "vends", price > $10
• May include quantity ("2x tickets"), ticket tier (VIP, GA), and event days

BUYER / WANTED (is_buyer_listing = true):
• Someone is LOOKING TO BUY tickets — do NOT classify as is_ticket
• English signals: "ISO", "WTB", "looking for", "need tickets", "anyone selling", \
"seeking", "wanted"
• French signals: "cherche", "recherche", "ISO", "je cherche des billets"
• Price is $0 or $1 (placeholder for wanted ads)
• Price and quantity may both be listed from the buyer's perspective

MERCHANDISE (is_merch = true):
• Physical items that are NOT event admission — fan gear, clothing, collectibles
• Examples: t-shirts, hoodies, crop tops, rave outfits, festival clothing, posters, \
albums, CDs, light sticks, glow sticks, wristbands, lanyards, hats, totems
• Note: festival clothing (rave wear, crop tops) is merch even if listed alongside an event name

WRONG CATEGORY (is_wrong_category = true):
• Completely unrelated items — keyword match in the title is coincidental
• Examples: kitchen appliances (pots, pans), pest/animal repellers, electronics, \
furniture, tools, vehicles
• These are NOT merch and NOT tickets

UNKNOWN (all flags false):
• Listing is too vague, deleted, or does not fit any category

━━━ FIELD EXTRACTION RULES ━━━

extracted_event: canonical event name if identifiable ("VELD", "Electric Island", \
"Osheaga", "Nocturnal Wonderland"). Use null if ambiguous or unrelated.

extracted_price: price PER TICKET as a number.
• If selling 2 tickets for $800 total → extracted_price = 400.0
• If price field shows total but description says "each" → use per-ticket price
• If buyer listing → null (buyer's budget is unreliable)
• If price is $0 or $1 → null (placeholder, not a real price)

face_value_price: only if seller EXPLICITLY states their original purchase price \
("paid $X", "face value $X", "original price $X"). Otherwise null.
face_value_mentioned: true if any face value / original price is mentioned, \
even if the exact number is unclear.

quantity: number of tickets being sold or sought as an integer.
• "2x tickets" → 2, "a pair" → 2, "3 tickets" → 3
• If clearly 1 ticket → 1. If not mentioned → null.

ticket_type: admission tier. Use exactly one of:
• "VIP" — any VIP, backstage, platinum, patron, premium tier
• "GA" — general admission, floor, lawn, regular
• "WEEKEND_PASS" — multi-day pass covering the full festival run
• "DAY_PASS" — single day of a multi-day festival (e.g. "Saturday only")
• "UNKNOWN" — tier not mentioned or unclear
Use null only if the listing is clearly not a ticket (merch, wrong category, etc).

event_days: for multi-day festivals, list the specific day(s) mentioned.
• Examples: ["Friday"], ["Saturday", "Sunday"], ["Day 1"], ["Day 2", "Day 3"]
• Use null if not a multi-day event, or if no specific day is mentioned.
• "Weekend pass" without specific days → null (not a specific day reference)

price_negotiable: true if listing uses "OBO", "or best offer", "negotiable", \
"flexible", "make an offer", or similar. False otherwise.

includes_extras: list any bundled extras mentioned that are NOT the ticket itself.
• Use these exact values: "parking_pass", "camping_pass", "shuttle", "hotel", \
"meet_and_greet", "locker", "fast_lane", "wristband_included"
• null if no extras mentioned.

seller_note: one short sentence capturing anything notable about logistics, urgency, \
or condition — e.g. "digital transfer via Ticketmaster", "pick up at venue only", \
"urgent — leaving the country", "slight crease on physical ticket".
• null if nothing notable beyond a standard sale.

confidence:
• "high" — listing clearly fits one category with no ambiguity
• "medium" — likely one category but some signal is missing or contradictory
• "low" — ambiguous, insufficient info, or unusual listing

reason: one sentence explaining your primary verdict (e.g. why is_ticket=true, \
or why something was flagged as wrong_category).

━━━ OUTPUT FORMAT ━━━
Return a JSON ARRAY with exactly one object per listing, in the same order as input.
Every object must include ALL fields below. Use null for optional numeric/string/array \
fields when the value is unknown or not applicable. Boolean fields are never null.

[
  {
    "is_ticket": boolean,
    "is_buyer_listing": boolean,
    "is_merch": boolean,
    "is_wrong_category": boolean,
    "extracted_event": string | null,
    "extracted_price": number | null,
    "face_value_price": number | null,
    "face_value_mentioned": boolean,
    "quantity": integer | null,
    "ticket_type": "VIP" | "GA" | "WEEKEND_PASS" | "DAY_PASS" | "UNKNOWN" | null,
    "event_days": array of strings | null,
    "price_negotiable": boolean,
    "includes_extras": array of strings | null,
    "seller_note": string | null,
    "confidence": "high" | "medium" | "low",
    "reason": string
  },
  ...
]

━━━ CALIBRATION EXAMPLES ━━━

Title: "2x VELD VIP Saturday $400 each OBO"  Price: 800  Description: "Selling 2 VIP \
Saturday tickets to VELD 2026. Paid $350 face value each. Digital transfer via \
Ticketmaster."
→ is_ticket=true, is_buyer_listing=false, is_merch=false, is_wrong_category=false, \
extracted_event="VELD", extracted_price=400.0, face_value_price=350.0, \
face_value_mentioned=true, quantity=2, ticket_type="VIP", event_days=["Saturday"], \
price_negotiable=true, includes_extras=null, seller_note="digital transfer via \
Ticketmaster", confidence="high", reason="Clearly selling 2 VIP Saturday tickets \
with face value disclosed and OBO noted."

Title: "Recherche 2 billets Electric Island"  Price: 1  Description: "Cherche 2 billets \
pour Electric Island dimanche. Payerai bon prix."
→ is_ticket=false, is_buyer_listing=true, is_merch=false, is_wrong_category=false, \
extracted_event="Electric Island", extracted_price=null, face_value_price=null, \
face_value_mentioned=false, quantity=2, ticket_type="UNKNOWN", event_days=["Sunday"], \
price_negotiable=false, includes_extras=null, seller_note=null, confidence="high", \
reason="French buyer listing — 'recherche/cherche billets' means looking for tickets."

Title: "VELD 2026 crop top rave outfit festival"  Price: 45  Description: "Brand new \
rave crop top, perfect for VELD or Electric Island. Never worn."
→ is_ticket=false, is_buyer_listing=false, is_merch=true, is_wrong_category=false, \
extracted_event=null, extracted_price=null, face_value_price=null, \
face_value_mentioned=false, quantity=null, ticket_type=null, event_days=null, \
price_negotiable=false, includes_extras=null, seller_note=null, confidence="high", \
reason="Festival clothing (rave crop top), not an admission ticket."

Title: "Ultrasonic animal repeller VELD pest control"  Price: 25  Description: \
"Electronic ultrasonic pest repeller, indoor/outdoor use."
→ is_ticket=false, is_buyer_listing=false, is_merch=false, is_wrong_category=true, \
extracted_event=null, extracted_price=null, face_value_price=null, \
face_value_mentioned=false, quantity=null, ticket_type=null, event_days=null, \
price_negotiable=false, includes_extras=null, seller_note=null, confidence="high", \
reason="Pest control device — event keyword in title is coincidental, unrelated item."

Title: "Osheaga weekend pass + camping + parking"  Price: 650  Description: "Full \
weekend pass for Osheaga 2026 with camping pass and parking included. GA. Firm price, \
no trades."
→ is_ticket=true, is_buyer_listing=false, is_merch=false, is_wrong_category=false, \
extracted_event="Osheaga", extracted_price=650.0, face_value_price=null, \
face_value_mentioned=false, quantity=1, ticket_type="WEEKEND_PASS", event_days=null, \
price_negotiable=false, includes_extras=["camping_pass", "parking_pass"], \
seller_note="firm price, no trades", confidence="high", \
reason="Weekend pass with camping and parking bundled, seller is firm on price."
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
