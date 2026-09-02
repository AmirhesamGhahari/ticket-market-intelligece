from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger


class SeatGeekClient:
    _BASE = "https://api.seatgeek.com/2"
    _PER_PAGE = 100
    _RETRY_DELAY = 15.0  # seconds to wait on 429

    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._http = httpx.Client(timeout=30)

    def get_listings(self, sg_event_id: int) -> list[dict[str, Any]]:
        """Fetch all current ticket listings for a SeatGeek event, paginating automatically."""
        logger.info(f"[SeatGeek] Fetching listings for event {sg_event_id}")
        listings: list[dict] = []
        page = 1

        while True:
            data = self._get(
                "/listings",
                params={"event_id": sg_event_id, "per_page": self._PER_PAGE, "page": page},
            )
            batch = data.get("listings") or []
            listings.extend(batch)

            meta = data.get("meta") or {}
            total_pages = meta.get("pages") or 1
            logger.debug(f"[SeatGeek] Page {page}/{total_pages} — {len(batch)} listings")

            if page >= total_pages or not batch:
                break
            page += 1

        logger.info(f"[SeatGeek] Done — {len(listings)} listings for event {sg_event_id}")
        return listings

    def search_events(self, query: str, city: str | None = None) -> list[dict[str, Any]]:
        """Search for events by name — useful for finding a SeatGeek event ID."""
        params: dict[str, Any] = {"q": query, "per_page": 20}
        if city:
            params["venue.city"] = city
        data = self._get("/events", params=params)
        return data.get("events") or []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = self._BASE + path
        all_params = {"client_id": self._client_id, **(params or {})}

        for attempt in range(3):
            try:
                resp = self._http.get(url, params=all_params)
            except httpx.RequestError as exc:
                logger.error(f"[SeatGeek] Request error on {path}: {exc}")
                raise

            if resp.status_code == 429:
                wait = self._RETRY_DELAY * (attempt + 1)
                logger.warning(f"[SeatGeek] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"[SeatGeek] Exceeded retries for {path}")
