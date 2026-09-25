from __future__ import annotations

from typing import Any

from apify_client import ApifyClient
from loguru import logger


class DatavoyantlabRunner:
    """Thin wrapper around the datavoyantlab/Facebook-marketplace-scraper Apify actor."""

    def __init__(self, api_token: str, actor_id: str) -> None:
        self._client = ApifyClient(api_token)
        self._actor_id = actor_id

    def run(self, run_input: dict[str, Any]) -> list[dict]:
        logger.info(f"[FB-Mkt] Calling actor {self._actor_id!r} with {len(run_input.get('urls', []))} URLs")
        try:
            run = self._client.actor(self._actor_id).call(run_input=run_input)
        except Exception as exc:
            logger.error(f"[FB-Mkt] Actor call failed: {exc}")
            raise

        try:
            items = list(self._client.dataset(run.default_dataset_id).iterate_items())
        except Exception as exc:
            logger.error(f"[FB-Mkt] Failed to fetch dataset: {exc}")
            raise

        logger.info(f"[FB-Mkt] Done — {len(items)} records retrieved")
        return items


def build_run_input(
    marketplace_urls: list[str],
    max_items: int,
    fetch_item_details: bool = False,
    deduplicate_across_runs: bool = False,
    stop_on_first_page_all_duplicates: bool = False,
) -> dict:
    """Build the actor run_input for the datavoyantlab actor."""
    return {
        "urls": marketplace_urls,
        "max_items": max_items,
        "fetch_item_details": fetch_item_details,
        "deduplicate_across_runs": deduplicate_across_runs,
        "stop_on_first_page_all_duplicates": stop_on_first_page_all_duplicates,
    }
