from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger


class SeatGeekClient:
    """SeatGeek public API client.

    Note: SeatGeek's public API does not expose individual ticket listings
    (section/row/price/quantity) — per their own docs, there are no plans to.
    The only pricing signal available is the aggregate `stats` object on an
    event (lowest/highest/average price, listing count).
    """

    _BASE = "https://api.seatgeek.com/2"
    _RETRY_DELAY = 15.0  # seconds to wait on 429

    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._http = httpx.Client(timeout=30)

    def get_event(self, sg_event_id: int) -> dict[str, Any]:
        """Fetch a single event, including its aggregate price `stats` object."""
        logger.info(f"[SeatGeek] Fetching event {sg_event_id}")
        return self._get(f"/events/{sg_event_id}")

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
