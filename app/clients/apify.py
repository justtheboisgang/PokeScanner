"""Apify client (§4.4).

Runs an actor synchronously and returns its dataset items. Cost is billed on two
axes against the same balance (plan credit + per-result actor fees), and
residential-proxy bandwidth is expensive — so `max_items` caps every run and the
poll queries only a curated subset of terms.
"""

from __future__ import annotations

import json

import httpx

from app.clients.exceptions import ClientError, QuotaExceededError, RateLimitError
from app.config import get_settings


class ApifyClient:
    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        settings = get_settings()
        self.token = token if token is not None else settings.apify_token
        self.base_url = (base_url or settings.apify_base_url).rstrip("/")
        # Token goes in the Authorization header, not the query string, so it
        # never lands in request logs.
        self._client = httpx.Client(
            base_url=self.base_url,
            transport=transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
        )

    def __enter__(self) -> "ApifyClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def run_actor_get_items(
        self, actor_id: str, run_input: dict, *, max_items: int | None = None
    ) -> list[dict]:
        """Run an actor and return dataset items (run-sync-get-dataset-items)."""
        params: dict[str, object] = {}
        if max_items is not None:
            params["maxItems"] = max_items

        resp = self._client.post(
            f"/acts/{actor_id}/run-sync-get-dataset-items",
            params=params,
            json=run_input,
        )
        if resp.status_code == 402:
            # Payment required — plan/usage limit reached. Stop, do not retry.
            raise QuotaExceededError("Apify usage limit reached (402)")
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise RateLimitError(
                "Apify rate limited",
                retry_after=float(retry_after) if retry_after else None,
            )
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, list):
            return body
        # Some responses wrap items; be defensive.
        if isinstance(body, dict) and isinstance(body.get("items"), list):
            return body["items"]
        raise ClientError(
            f"Unexpected Apify response shape: {json.dumps(body)[:200]}"
        )
