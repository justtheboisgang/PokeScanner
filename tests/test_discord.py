"""Discord notifier + embed (§8)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.alerts.discord import AlertContent, DiscordNotifier, build_embed


def _content(price=Decimal("50"), image="https://img/1.jpg"):
    return AlertContent(
        title="Alte Pokemon Karten Sammlung",
        url="https://kleinanzeigen.de/x",
        price=price,
        currency="EUR",
        location="Berlin",
        channel="Kleinanzeigen",
        matched_search_term="alte pokemon karten",
        image_url=image,
    )


def test_embed_contains_required_fields_and_contact_message():
    embed = build_embed(_content())
    names = {f["name"] for f in embed["fields"]}
    assert any("Preis" in n for n in names)
    assert any("Gewinn" in n for n in names)
    assert any("Kaskade" in n for n in names)
    assert any("Kontaktnachricht" in n for n in names)
    assert embed["url"] == "https://kleinanzeigen.de/x"
    assert embed["image"]["url"] == "https://img/1.jpg"
    # Phase 2: unbewertbar by default.
    profit = next(f["value"] for f in embed["fields"] if "Gewinn" in f["name"])
    assert "unbewertbar" in profit


def test_price_unknown_rendering():
    embed = build_embed(_content(price=None))
    price = next(f["value"] for f in embed["fields"] if "Preis" in f["name"])
    assert price == "Preis unbekannt"


def test_free_giveaway_rendering():
    embed = build_embed(_content(price=Decimal("0")))
    price = next(f["value"] for f in embed["fields"] if "Preis" in f["name"])
    assert "verschenken" in price.lower()


def test_send_returns_message_id_and_uses_wait():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["wait"] = request.url.params.get("wait")
        seen["json"] = request.read().decode()
        return httpx.Response(200, json={"id": "998877"})

    notifier = DiscordNotifier(
        "https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
    )
    msg_id = notifier.send(_content())
    assert msg_id == "998877"
    assert seen["wait"] == "true"
    assert "embeds" in seen["json"]


def test_send_suppresses_mentions():
    import json
    from dataclasses import replace

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={"id": "1"})

    notifier = DiscordNotifier(
        "https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
    )
    # Attacker-controlled title must never ping.
    notifier.send(replace(_content(), title="@everyone free cards"))
    assert seen["body"]["allowed_mentions"] == {"parse": []}


def test_send_noop_when_disabled():
    notifier = DiscordNotifier("")
    assert notifier.enabled is False
    assert notifier.send(_content()) is None
