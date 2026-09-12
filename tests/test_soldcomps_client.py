"""SoldComps client edge cases (§4.2)."""

from __future__ import annotations

import httpx
import pytest

from app.clients.exceptions import QuotaExceededError, RateLimitError
from app.clients.soldcomps import SoldCompsClient


def _client(handler, **kw) -> SoldCompsClient:
    return SoldCompsClient(
        api_key="sc_test",
        base_url="https://api.sold-comps.com",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,  # never sleep in tests
        **kw,
    )


def test_pagination_follows_has_next_page_not_total_items():
    # totalItems is the CURRENT page count, never the grand total. Pagination
    # must be driven purely off hasNextPage across pages.
    pages = {
        "1": {
            "items": [{"soldPrice": 10}, {"soldPrice": 11}],
            "totalItems": 2,
            "hasNextPage": True,
            "totalResults": "40+",
        },
        "2": {
            "items": [{"soldPrice": 12}],
            "totalItems": 1,
            "hasNextPage": False,
            "totalResults": "40+",
        },
    }

    seen_params = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=pages[page])

    items = _client(handler).scrape_sold("glurak")
    assert [i["soldPrice"] for i in items] == [10, 11, 12]
    # hydrateBoa mandatory on every sold request (§4.2.2).
    assert all(p.get("hydrateBoa") == "true" for p in seen_params)
    # Two pages fetched, driven by hasNextPage.
    assert [p["page"] for p in seen_params] == ["1", "2"]


def test_empty_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "hasNextPage": False})

    assert _client(handler).scrape_sold("nothing") == []


def test_missing_items_key_is_safe():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hasNextPage": False})

    assert _client(handler).scrape_sold("weird") == []


def test_429_quota_exceeded_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"code": "quota_exceeded"})

    with pytest.raises(QuotaExceededError):
        _client(handler).scrape_sold("glurak")
    assert calls["n"] == 1  # no retry


def test_429_rate_limited_carries_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"code": "rate_limited"}, headers={"Retry-After": "7"}
        )

    with pytest.raises(RateLimitError) as exc:
        _client(handler).scrape_sold("glurak")
    assert exc.value.retry_after == 7.0


def test_credit_source_header_on_batch_only():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["credit"] = request.headers.get("X-Credit-Source")
        return httpx.Response(200, json={"items": [], "hasNextPage": False})

    # batch=True (scheduled jobs) -> subscription-only header present (§4.2.3).
    _client(handler, credit_source="subscription-only").scrape_sold("x", batch=True)
    assert seen["credit"] == "subscription-only"

    _client(handler, credit_source="subscription-only").scrape_page(
        "x", sold=True, batch=False
    )
    assert seen["credit"] is None


def test_cookies_header_only_when_enabled():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cookies"] = request.headers.get("X-eBay-Cookies")
        return httpx.Response(200, json={"items": [], "hasNextPage": False})

    # Default OFF.
    _client(handler).scrape_ask("x")
    assert seen["cookies"] is None

    _client(handler, use_cookies=True, ebay_cookies="sid=abc").scrape_ask("x")
    assert seen["cookies"] == "sid=abc"


def test_ask_does_not_send_hydrate_boa():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [], "hasNextPage": False})

    _client(handler).scrape_ask("x")
    assert "hydrateBoa" not in seen["params"]
    assert seen["params"]["sold"] == "false"


def test_max_pages_guard_stops_runaway_pagination():
    # A server that always claims hasNextPage must not loop forever.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"items": [{"soldPrice": 1}], "hasNextPage": True}
        )

    items = _client(handler).scrape_sold("x", max_pages=3)
    assert len(items) == 3
