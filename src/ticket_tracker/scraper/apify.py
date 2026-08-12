from __future__ import annotations

from typing import Any

from apify_client import ApifyClient
from loguru import logger


class ApifyRunner:
    def __init__(self, api_token: str, actor_id: str) -> None:
        self._client = ApifyClient(api_token)
        self._actor_id = actor_id

    def run(self, run_input: dict[str, Any]) -> list[dict]:
        logger.info(f"[Apify] Calling actor {self._actor_id!r}")
        try:
            run = self._client.actor(self._actor_id).call(run_input=run_input)
        except Exception as exc:
            logger.error(f"[Apify] Actor call failed: {exc}")
            raise

        dataset_id = run["defaultDatasetId"]
        try:
            items = list(self._client.dataset(dataset_id).iterate_items())
        except Exception as exc:
            logger.error(f"[Apify] Failed to fetch dataset {dataset_id}: {exc}")
            raise

        logger.info(f"[Apify] Done — {len(items)} records retrieved")
        return items
