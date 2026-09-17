# StubHub Listing Extraction — Method Documentation

## Overview

This document records the confirmed method for extracting ticket listing data from StubHub event pages without using the official API. It covers the full discovery, the two-phase scraping strategy, the exact API behavior, Scrapfly configuration, and the complete algorithm for a production scraper.

---

## Background: What StubHub's Tech Stack Looks Like

StubHub event pages are **Single Page Applications (React/Voyage)**. The raw HTML served is nearly empty:

```html
<div id="app"></div>
```

React hydrates the DOM after JavaScript runs. This means:
- Standard HTML scrapers see nothing useful
- Headless browsers are required for full rendering
- But: **the first 10 listings are server-side embedded in the initial HTML** — no JavaScript execution required to get them

StubHub uses **DataDome** enterprise anti-bot protection. DataDome:
- Blocks headless Chromium browsers based on fingerprinting (even through residential proxies)
- Issues session cookies tied to the IP that passed the challenge
- Rejects requests where the IP doesn't match the original validated session

---

## Key Discovery: Dual-Mode Endpoint

StubHub uses **the same URL** for two different purposes depending on the HTTP method:

| Method | Returns |
|--------|---------|
| `GET`  | Full HTML page — first 10 listings embedded in a `<script>` tag |
| `POST` | JSON response — next batch of 10 listings (pagination) |

The POST endpoint is **not a separate API URL**. It is the same event page URL with a JSON body containing `"Method": "IndexShGridOnly"`.

### Confirmed Event Example

```
URL:  https://www.stubhub.com/olivia-rodrigo-toronto-tickets-10-26-2026/event/161041533/?quantity=0
Event ID: 161041533
Total listings: 205
Page size: 10 (fixed)
Pages needed: 21 (first from GET, pages 2–21 from POST)
```

---

## Phase 1 — GET Request (First 10 Listings + Session Setup)

### Purpose
1. Establish a valid DataDome session cookie
2. Extract the first 10 listings embedded in the HTML
3. Extract metadata: `totalListings`, `pageVisitId`, CSRF token, `CategoryId`

### Scrapfly Configuration

```
Method:        GET
URL:           https://www.stubhub.com/{event-slug}/event/{eventId}/?quantity=0
asp:           true         ← bypasses DataDome
render_js:     false        ← NOT needed; data is in raw HTML (saves cost)
session:       {session_id} ← e.g. "stubhub_sess_1" — must match POST requests
sticky_proxy:  true         ← IP must stay the same across all requests in session
proxy_pool:    public_datacenter_pool
country:       US           ← StubHub.com is US-only (redirects from .ca)
cost_budget:   20           ← safety cap in Scrapfly credits
```

### Where the First 10 Listings Live in the HTML

Search the HTML for a `<script>` tag containing `"appName":"viagogo-event"`:

```html
<script type="text/javascript">
  window.digitalData = {..., "appName":"viagogo-event", "grid":{"items":[...]}, ...}
</script>
```

Extract by parsing the JSON object from this script block. The listings array is at:
```
window.digitalData → grid → items → [ listing objects... ]
```

### Other Values to Extract from the GET Response

| Value | Location in HTML |
|-------|-----------------|
| `totalListings` | Same JSON: `grid.totalListings` |
| `pageVisitId` | Same JSON: `pageVisitId` (used in POST body) |
| `CategoryId` | Same JSON: event metadata (needed in POST body) |
| CSRF token | `<input type="hidden" id="x-csrf-token" value="...">` |
| `datadome` cookie | Set in response `Set-Cookie` header (managed by Scrapfly session) |

---

## Phase 2 — POST Requests (Remaining Listings)

### Purpose
Fetch listings in batches of 10 for pages 2 through N, where:
```
N = ceil(totalListings / 10)
```

### Scrapfly Configuration

```
Method:        POST
URL:           https://www.stubhub.com/{event-slug}/event/{eventId}/?quantity=0
asp:           true
render_js:     false
session:       {same session_id as GET}
sticky_proxy:  true         ← REQUIRED — DataDome ties cookie to original IP
proxy_pool:    public_datacenter_pool
country:       US
```

**Critical:** The session name and sticky proxy must match the GET request. Without this, DataDome rejects the POST because the IP has changed and the cookie is no longer valid.

### Request Body

```json
{
    "Method": "IndexShGridOnly",
    "CurrentPage": 2,
    "PageSize": 10,
    "Quantity": 0,
    "ShowAllTickets": true,
    "SortBy": "RECOMMENDED",
    "SortDirection": 1,
    "FilterSortSessionId": "RANDOM-UUID-HERE",
    "PageVisitId": "PAGE-VISIT-ID-FROM-GET"
}
```

### Field Reference

| Field | Required | Notes |
|-------|----------|-------|
| `Method` | YES | Must be `"IndexShGridOnly"` — tells server to return listing grid JSON |
| `CurrentPage` | YES | Starts at 2 (page 1 comes from GET). Increment per request. |
| `PageSize` | YES | Use `10`. StubHub's fixed page size. |
| `Quantity` | YES | `0` = any quantity. Match the `?quantity=` URL param. |
| `ShowAllTickets` | YES | `true`. If `false`, results are filtered and incomplete. |
| `SortBy` | Optional | `"RECOMMENDED"` matches default browser sort. |
| `SortDirection` | Optional | `1` = ascending. |
| `FilterSortSessionId` | Optional | Generate a fresh `uuid.uuid4()` per scrape session. Server does not validate. |
| `PageVisitId` | Optional | Use value from GET response JSON. Can also be a fresh UUID. |
| `CategoryId` | Optional | Extract from GET response. Ties to seating map. |
| `PriceRange` | OMIT | Browser sends `"0,100"` — this limits results. Do not include unless filtering intentionally. |
| All empty-string fields | OMIT | `Rows`, `Sections`, `Seats`, etc. are browser filter state. Omit for full results. |

### Response Format

The POST returns `application/json`:

```json
{
    "grid": {
        "items": [ ...listing objects... ],
        "totalListings": 205,
        "pageSize": 10,
        "currentPage": 2
    }
}
```

Listings are at `response["grid"]["items"]`.

---

## Listing Object Schema

Each listing item returned by both GET (embedded) and POST:

```python
{
    "listingId":              "string — unique listing identifier",
    "eventId":                "int",
    "section":                "string — e.g. 'Floor 1', 'Section 108'",
    "ticketClassName":        "string — e.g. 'General Admission', 'VIP'",
    "row":                    "string — row letter/number, null for GA",
    "seatFrom":               "int — first seat number",
    "seatTo":                 "int — last seat number",
    "availableTickets":       "int — total in listing",
    "availableQuantities":    "[int] — e.g. [1, 2, 4]",
    "rawPrice":               "float — price per ticket in listing currency",
    "price":                  "string — formatted display price",
    "formattedTotalPrice":    "string — total with fees",
    "listingCurrencyCode":    "string — e.g. 'USD'",
    "faceValue":              "float — original face value",
    "faceValueCurrencyCode":  "string",
    "ticketTypeName":         "string — e.g. 'Mobile', 'E-Ticket', 'Paper'",
    "inventoryListingScore":  {
        "dealScore":   "string — e.g. 'Great Deal'",
        "starRating":  "float"
    },
    "listingNotes":           "[{formattedListingNoteContent, showToBuyer, ...}]",
    "isCheapestListing":      "bool",
    "isSponsored":            "bool",
    "createdDateTime":        "ISO timestamp"
}
```

---

## Cost Model (Scrapfly Credits)

| Request Type | `render_js` | `asp` | Approx Credits |
|---|---|---|---|
| GET page (1×) | false | true | ~5–10 |
| POST pagination (per page) | false | true | ~5–10 |
| **Total for 205 listings (21 requests)** | — | — | **~105–210** |

Compare to: browser rendering each page would cost 10–20× more.

**Key cost levers:**
- `render_js=false` saves the most — React hydration not needed at any step
- `public_datacenter_pool` is cheapest proxy tier
- `cost_budget=N` prevents runaway credit spending (set per scrape job)

---

## Complete Algorithm (Pseudocode)

```python
import uuid
import math
import json
import re

SCRAPFLY_KEY = "your_key_here"

def scrape_stubhub_event(event_url: str, quantity: int = 0) -> list[dict]:
    session_id = f"stubhub_{uuid.uuid4().hex[:8]}"
    base_url = f"{event_url.rstrip('/')}?quantity={quantity}"
    all_listings = []

    # --- Phase 1: GET ---
    get_response = scrapfly_get(
        url=base_url,
        method="GET",
        asp=True,
        render_js=False,
        session=session_id,
        sticky_proxy=True,
    )
    html = get_response.content

    # Extract embedded JSON from script tag
    match = re.search(r'"appName":"viagogo-event".*?"grid":\s*(\{.*?\})\s*,\s*"', html, re.DOTALL)
    # (use a proper JSON extractor in production — see implementation notes)

    embedded_data = extract_grid_json(html)
    items = embedded_data["items"]
    total_listings = embedded_data["totalListings"]
    page_visit_id = extract_page_visit_id(html)

    all_listings.extend(items)

    total_pages = math.ceil(total_listings / 10)

    # --- Phase 2: POST for pages 2..N ---
    for page in range(2, total_pages + 1):
        post_response = scrapfly_post(
            url=base_url,
            session=session_id,
            sticky_proxy=True,
            asp=True,
            render_js=False,
            body={
                "Method": "IndexShGridOnly",
                "CurrentPage": page,
                "PageSize": 10,
                "Quantity": quantity,
                "ShowAllTickets": True,
                "SortBy": "RECOMMENDED",
                "SortDirection": 1,
                "FilterSortSessionId": str(uuid.uuid4()).upper(),
                "PageVisitId": page_visit_id,
            }
        )
        data = post_response.json()
        all_listings.extend(data["grid"]["items"])

    return [parse_listing(item, event_url) for item in all_listings]
```

---

## Parsing Listings

```python
def parse_listing(item: dict, source_url: str) -> dict:
    notes = [
        n["formattedListingNoteContent"]
        for n in item.get("listingNotes", [])
        if n.get("showToBuyer")
    ]
    score = item.get("inventoryListingScore", {})
    return {
        "listing_id":           item.get("listingId") or item.get("id"),
        "event_id":             item.get("eventId"),
        "source_url":           source_url,
        "section":              item.get("section"),
        "ticket_class":         item.get("ticketClassName"),
        "row":                  item.get("row"),
        "seat_from":            item.get("seatFrom"),
        "seat_to":              item.get("seatTo"),
        "available_tickets":    item.get("availableTickets"),
        "available_quantities": item.get("availableQuantities", []),
        "raw_price":            item.get("rawPrice"),
        "display_price":        item.get("price"),
        "total_price":          item.get("formattedTotalPrice"),
        "currency":             item.get("listingCurrencyCode"),
        "face_value":           item.get("faceValue"),
        "face_value_currency":  item.get("faceValueCurrencyCode"),
        "ticket_type":          item.get("ticketTypeName"),
        "deal_score":           score.get("dealScore"),
        "star_rating":          score.get("starRating"),
        "listing_notes":        notes,
        "is_cheapest":          item.get("isCheapestListing"),
        "is_sponsored":         item.get("isSponsored"),
        "created_at":           item.get("createdDateTime"),
    }
```

---

## Implementation Notes

### Extracting the Embedded Grid JSON from HTML

The `window.digitalData` object is large. The safest extraction approach:

```python
import re, json

def extract_grid_json(html: str) -> dict:
    # Find the script block containing the app data
    match = re.search(
        r'window\.digitalData\s*=\s*(\{.+?\});\s*</script>',
        html,
        re.DOTALL
    )
    if not match:
        raise ValueError("Could not find embedded listing data in HTML")
    data = json.loads(match.group(1))
    return data["grid"]
```

If `window.digitalData` is minified without spaces, adjust the regex. Alternatively, use a JSON-aware parser like `chompjs` or `demjson3` to handle JS object literals.

### Session Lifecycle

- Create a new `session_id` per event scrape (don't reuse across events)
- Sessions in Scrapfly expire after ~10 minutes of inactivity
- For events with many pages, ensure all POST requests complete within the session window
- If a POST fails mid-run, start a new session from scratch (re-GET the page)

### StubHub Domain

- StubHub.ca (Canada) redirects to stubhub.com (US) when accessed through a US IP
- Always use the `stubhub.com` URL directly in the scraper
- Set `country=US` in Scrapfly to get a US IP

### Rate Limiting

- Add a short delay between POST requests (0.5–1s) to avoid triggering rate limits
- Do not reuse session IDs across different events
- For multiple events, use separate sessions with separate IDs

---

## What Was Tried and Rejected

| Approach | Outcome | Reason Rejected |
|---|---|---|
| Apify Playwright (Chromium) + residential proxy | DataDome CAPTCHA | Headless Chromium fingerprint detected by DataDome even through proxy |
| Scrapfly GET + `wait_for_selector: #listings-container` | Timeout after 15s | `#listings-container` is rendered by React; React never hydrates in Scrapfly's env |
| Scrapfly cold POST (no prior GET session) | `ASP::SHIELD_PROTECTION_FAILED` | DataDome rejects POST with no prior validated session cookie |
| Scrapfly GET+POST without sticky proxy | `ASP::SHIELD_PROTECTION_FAILED` | DataDome cookie tied to original IP; different IP on POST = rejected |
| Scrapfly GET+POST with session + sticky proxy | **SUCCESS** | DataDome cookie maintained across requests on same IP |

---

## Confirmed Working Configuration Summary

```
Provider:     Scrapfly
asp:          true   (DataDome bypass)
render_js:    false  (not needed at any step)
sticky_proxy: true   (REQUIRED — DataDome ties cookie to IP)
session:      {unique per event scrape}
proxy_pool:   public_datacenter_pool
country:      US

Step 1: GET  event URL → extract first 10 listings + metadata
Step 2: POST event URL × (N-1) pages → extract remaining listings
        Body: {"Method": "IndexShGridOnly", "CurrentPage": N, ...}
```
