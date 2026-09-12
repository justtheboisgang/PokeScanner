"""TCGdex client edge cases (§4.1)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.clients.tcgdex import TCGdexClient


def _client(handler) -> TCGdexClient:
    return TCGdexClient(
        base_url="https://api.tcgdex.net/v2",
        primary_lang="de",
        transport=httpx.MockTransport(handler),
    )


def test_pricing_parsed_when_present():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "base1-4",
                "name": "Glurak",
                "pricing": {
                    "cardmarket": {
                        "avg": 250.0,
                        "low": 180.0,
                        "trend": 240.5,
                        "avg7": 238.0,
                        "avg30": 245.0,
                        "trend-holo": 300.0,
                        "avg7-holo": 295.0,
                    }
                },
            },
        )

    cm = _client(handler).get_cardmarket_pricing("base1-4")
    assert cm is not None
    assert cm.trend == Decimal("240.5")
    assert cm.avg7 == Decimal("238.0")
    assert cm.trend_holo == Decimal("300.0")


def test_missing_pricing_block_returns_none():
    # A card not listed on any marketplace has NO `pricing` key at all (§4.1).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "x", "name": "y"})

    assert _client(handler).get_cardmarket_pricing("x") is None


def test_missing_cardmarket_subblock_returns_none():
    # pricing exists but the Cardmarket provider block is absent.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "x", "pricing": {"tcgplayer": {"normal": {}}}}
        )

    assert _client(handler).get_cardmarket_pricing("x") is None


def test_language_fallback_de_to_en():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/de/cards/" in request.url.path:
            return httpx.Response(404, json={"error": "not found"})
        if "/en/cards/" in request.url.path:
            return httpx.Response(200, json={"id": "x", "name": "Charizard"})
        return httpx.Response(500)

    card, lang = _client(handler).get_card_with_fallback("x")
    assert card is not None
    assert card["name"] == "Charizard"
    assert lang == "en"


def test_get_card_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert _client(handler).get_card("nope") is None
