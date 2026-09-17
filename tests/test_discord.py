"""Discord notifier + embed (§8)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

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


# --- Rate-Limit: 429 aussitzen statt Alarm verlieren -----------------------


def test_429_is_waited_out_and_retried():
    """Discord drosselt hart — ein Alarm darf daran nicht verloren gehen."""
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"retry_after": 1.25, "global": False})
        return httpx.Response(200, json={"id": "msg-1"})

    notifier = DiscordNotifier(
        "https://discord.test/hook",
        transport=httpx.MockTransport(handler),
        min_interval=0,
        sleep=slept.append,
    )
    assert notifier.send(_content()) == "msg-1"
    assert calls["n"] == 2
    assert slept == [1.25]  # exakt so lange wie Discord verlangt


def test_429_falls_back_to_retry_after_header():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="nope")
        return httpx.Response(200, json={"id": "m"})

    notifier = DiscordNotifier(
        "https://discord.test/hook",
        transport=httpx.MockTransport(handler),
        min_interval=0,
        sleep=slept.append,
    )
    notifier.send(_content())
    assert slept == [2.0]


def test_429_gives_up_after_max_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"retry_after": 0.1})

    notifier = DiscordNotifier(
        "https://discord.test/hook",
        transport=httpx.MockTransport(handler),
        min_interval=0,
        max_retries=2,
        sleep=lambda _s: None,
    )
    with pytest.raises(httpx.HTTPStatusError):
        notifier.send(_content())


def test_requests_are_spaced_out():
    """Mit Mindestabstand entstehen die 429 gar nicht erst."""
    slept: list[float] = []
    clock = {"t": 0.0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "m"})

    notifier = DiscordNotifier(
        "https://discord.test/hook",
        transport=httpx.MockTransport(handler),
        min_interval=0.6,
        sleep=slept.append,
        monotonic=lambda: clock["t"],
    )
    notifier.send(_content())
    assert slept == []          # erster Request wartet nie
    notifier.send(_content())
    assert slept == [0.6]       # zweiter haelt den Abstand ein
