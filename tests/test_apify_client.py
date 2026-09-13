"""Apify client (§4.4)."""

from __future__ import annotations

import httpx
import pytest

from app.clients.apify import ApifyClient
from app.clients.exceptions import QuotaExceededError, RateLimitError


def _client(handler) -> ApifyClient:
    return ApifyClient(
        token="apify_test",
        base_url="https://api.apify.com/v2",
        transport=httpx.MockTransport(handler),
    )


def test_returns_dataset_items_and_sends_input_and_max_items():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["maxItems"] = request.url.params.get("maxItems")
        seen["auth"] = request.headers.get("Authorization")
        seen["token_in_url"] = request.url.params.get("token")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json=[{"adId": "1"}, {"adId": "2"}])

    items = _client(handler).run_actor_get_items(
        "user~actor", {"search": "alte pokemon karten"}, max_items=40
    )
    assert [i["adId"] for i in items] == ["1", "2"]
    assert seen["path"].endswith("/acts/user~actor/run-sync-get-dataset-items")
    assert seen["maxItems"] == "40"
    # Token travels in the header, never the URL.
    assert seen["auth"] == "Bearer apify_test"
    assert seen["token_in_url"] is None
    assert "alte pokemon karten" in seen["body"]


def test_402_usage_limit_raises_quota():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "usage limit"})

    with pytest.raises(QuotaExceededError):
        _client(handler).run_actor_get_items("a", {})


def test_429_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "12"})

    with pytest.raises(RateLimitError) as exc:
        _client(handler).run_actor_get_items("a", {})
    assert exc.value.retry_after == 12.0


def test_empty_dataset():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    assert _client(handler).run_actor_get_items("a", {}) == []
