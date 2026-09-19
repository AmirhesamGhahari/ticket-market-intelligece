from __future__ import annotations

from typing import Any

from apify_client import ApifyClient
from loguru import logger


class FuturafreeRunner:
    """Thin wrapper around the futurafree/facebook-marketplace-scraper-discord-alerts Apify actor."""

    def __init__(self, api_token: str, actor_id: str) -> None:
        self._client = ApifyClient(api_token)
        self._actor_id = actor_id

    def run(self, run_input: dict[str, Any]) -> list[dict]:
        logger.info(f"[FB-Mkt] Calling actor {self._actor_id!r}")
        try:
            run = self._client.actor(self._actor_id).call(run_input=run_input)
        except Exception as exc:
            logger.error(f"[FB-Mkt] Actor call failed: {exc}")
            raise

        try:
            items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())
        except Exception as exc:
            logger.error(f"[FB-Mkt] Failed to fetch dataset: {exc}")
            raise

        logger.info(f"[FB-Mkt] Done — {len(items)} records retrieved")
        return items


def build_run_input(
    search_terms: list[str],
    latitude: str,
    longitude: str,
    min_price: str,
    max_price: str,
    days_listed: int,
    listings_per_search: int,
    search_radius_km: int | None = None,
    use_deduplication: bool = False,
    filter_keywords: list[str] | None = None,
) -> dict:
    """Build the actor run_input for the futurafree actor.

    minPrices, maxPrices, daysListed, and searchRadii must be parallel arrays
    matching the order of searchTerms.
    """
    n = len(search_terms)
    run_input: dict = {
        "searchTerms": search_terms,
        "minPrices": [min_price] * n,
        "maxPrices": [max_price] * n,
        "daysListed": [str(days_listed)] * n,
        "latitude": latitude,
        "longitude": longitude,
        "listingsPerSearch": listings_per_search,
        "useDeduplication": use_deduplication,
    }
    if search_radius_km is not None:
        capped = min(int(search_radius_km), 130)
        run_input["searchRadii"] = [str(capped)] * n
    if filter_keywords:
        run_input["filterKeywords"] = filter_keywords

    return run_input
