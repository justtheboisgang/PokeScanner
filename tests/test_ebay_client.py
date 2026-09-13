"""eBay Browse client (§4.3)."""

from __future__ import annotations

import httpx
import pytest

from app.clients.ebay import EbayBrowseClient
from app.clients.exceptions import QuotaExceededError, RateLimitError


def _client(handler) -> EbayBrowseClient:
    return EbayBrowseClient(
        client_id="cid",
        client_secret="secret",
        base_url="https://api.ebay.com",
        oauth_url="https://api.ebay.com/identity/v1/oauth2/token",
        marketplace="EBAY_DE",
        transport=httpx.MockTransport(handler),
    )


def test_token_cached_and_search_returns_summaries():
    calls = {"token": 0, "search": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            calls["token"] += 1
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        if "item_summary/search" in request.url.path:
            calls["search"] += 1
            assert request.headers["Authorization"] == "Bearer tok"
            assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_DE"
            return httpx.Response(200, json={"itemSummaries": [{"itemId": "1"}, {"itemId": "2"}]})
        return httpx.Response(404)

    client = _client(handler)
    a = client.search_active("glurak", limit=10)
    b = client.search_active("bisaflor", limit=10)
    assert [i["itemId"] for i in a] == ["1", "2"]
    assert len(b) == 2
    assert calls["token"] == 1  # token cached across searches
    assert calls["search"] == 2


def test_empty_summaries():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(200, json={})

    assert _client(handler).search_active("nothing") == []


def test_403_quota():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(403, json={"errors": []})

    with pytest.raises(QuotaExceededError):
        _client(handler).search_active("x")


def test_429_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(429)

    with pytest.raises(RateLimitError):
        _client(handler).search_active("x")
