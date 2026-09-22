from __future__ import annotations

import json
import math
import re
import secrets

import httpx
from loguru import logger

SCRAPFLY_URL = "https://api.scrapfly.io/scrape"


def scrape_event(
    api_key: str,
    event_url: str,
    max_listings: int = 200,
) -> list[dict]:
    """Scrape all ticket listings for one StubHub event.

    Phase 1: GET the event page (render_js=False) to extract the first batch
    of listings from the index-data script tag and get the total count.

    Phase 2: POST to the same URL with Method=IndexShGridOnly for each
    subsequent page, using the same Scrapfly session (sticky proxy) so
    DataDome cookies from phase 1 are carried forward.
    """
    session_id = f"stubhub_{secrets.token_hex(4)}"

    # ── Phase 1: GET ──────────────────────────────────────────────────────────
    logger.info(f"[StubHub] GET {event_url}")
    html = _scrapfly_get(api_key, event_url, session_id)

    grid = _extract_grid(html)
    all_items: list[dict] = list(grid.get("items", []))
    total = int(grid.get("totalListingsCount", 0))
    logger.info(f"[StubHub] {total} total listings, got first {len(all_items)} from HTML")

    pages_needed = math.ceil(min(total, max_listings) / 10)

    # ── Phase 2: POST pages 2..N ──────────────────────────────────────────────
    for page in range(2, pages_needed + 1):
        logger.info(f"[StubHub] POST page {page}/{pages_needed}")
        body = json.dumps({
            "Method": "IndexShGridOnly",
            "CurrentPage": page,
            "PageSize": 10,
            "Quantity": 0,
            "ShowAllTickets": True,
            "SortBy": "RECOMMENDED",
            "SortDirection": 1,
        })
        try:
            content = _scrapfly_post(api_key, event_url, session_id, body)
            data = json.loads(content)
            # IndexShGridOnly returns items at root; HTML page wraps them under "grid"
            items = data.get("items") or data.get("grid", {}).get("items", [])
            logger.info(f"[StubHub] Page {page}: got {len(items)} items (response keys: {list(data.keys())})")
            if not items:
                logger.warning(f"[StubHub] Page {page}: empty items — response snippet: {content[:300]}")
            all_items.extend(items)
        except json.JSONDecodeError as exc:
            logger.warning(f"[StubHub] Page {page} JSON parse failed: {exc} — content snippet: {content[:300] if 'content' in dir() else 'N/A'}")
            continue
        except Exception as exc:
            logger.warning(f"[StubHub] Page {page} failed: {exc} — skipping")
            continue

        if len(all_items) >= max_listings:
            break

    logger.info(f"[StubHub] Scraped {len(all_items)} listings total")
    return all_items[:max_listings]


# ── Scrapfly helpers ───────────────────────────────────────────────────────────


def _base_params(api_key: str, url: str, session_id: str) -> dict:
    return {
        "key": api_key,
        "url": url,
        "unblocker": "true",
        "render_js": "false",
        "retry": "false",
        "session": session_id,
        "proxy_pool": "public_datacenter_pool",
        "country": "us",
        "timeout": "75000",
    }


def _scrapfly_get(api_key: str, url: str, session_id: str) -> str:
    params = _base_params(api_key, url, session_id)
    resp = httpx.get(SCRAPFLY_URL, params=params, timeout=120)
    resp.raise_for_status()
    return _unwrap(resp.json(), url)


def _scrapfly_post(api_key: str, url: str, session_id: str, body: str) -> str:
    params = _base_params(api_key, url, session_id)
    resp = httpx.post(
        SCRAPFLY_URL,
        params=params,
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=120,
    )
    resp.raise_for_status()
    return _unwrap(resp.json(), url)


def _unwrap(response: dict, url: str) -> str:
    result = response.get("result", {})
    status = result.get("status_code")
    if status != 200:
        error = response.get("error", {})
        raise RuntimeError(
            f"Scrapfly upstream {status} for {url}: {error.get('message', 'unknown')}"
        )
    return result["content"]


# ── HTML extraction ────────────────────────────────────────────────────────────


def _extract_grid(html: str) -> dict:
    """Extract the grid object by scanning all application/json script tags.

    Scans every <script type="application/json"> block in document order and
    returns the grid from the first one whose parsed content contains
    grid.items (a list). This is intentionally ID-agnostic so it survives
    StubHub renaming or reordering their embedded data blocks.
    """
    for m in re.finditer(
        r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw.startswith("{"):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        grid = data.get("grid")
        if grid and isinstance(grid.get("items"), list):
            return grid

    raise ValueError(
        "No <script type='application/json'> block with grid.items found in StubHub HTML"
    )
