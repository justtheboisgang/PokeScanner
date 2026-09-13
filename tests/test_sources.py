"""Source normalization (§4.3, §4.4) + build_sources (Phase 5)."""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.ingest.ebay_browse import normalize_ebay_item
from app.ingest.kleinanzeigen import normalize_apify_item
from app.ingest.sources import build_sources
from app.models.enums import Channel


def test_normalize_ebay_item():
    item = {
        "itemId": "v1|123|0",
        "title": "Glurak Holo Base Set",
        "price": {"value": "199.99", "currency": "EUR"},
        "itemWebUrl": "https://ebay.de/itm/123",
        "image": {"imageUrl": "https://i.ebayimg.com/1.jpg"},
        "thumbnailImages": [{"imageUrl": "https://i.ebayimg.com/2.jpg"}],
        "itemLocation": {"postalCode": "10115", "country": "DE"},
    }
    n = normalize_ebay_item(item)
    assert n is not None
    assert n.channel == Channel.EBAY_BROWSE
    assert n.external_id == "v1|123|0"
    assert n.price == Decimal("199.99")
    assert n.currency == "EUR"
    assert n.images == ["https://i.ebayimg.com/1.jpg", "https://i.ebayimg.com/2.jpg"]
    assert "10115" in n.location


def test_normalize_ebay_item_missing_fields():
    assert normalize_ebay_item({"title": "x"}) is None
    assert normalize_ebay_item({"itemId": "1"}) is None


def test_willhaben_reuses_apify_normalizer():
    item = {
        "adId": "w1",
        "title": "Pokemon Sammlung",
        "price": "80 €",
        "location": "Wien",
        "url": "https://willhaben.at/w1",
    }
    n = normalize_apify_item(item, Channel.WILLHABEN)
    assert n is not None
    assert n.channel == Channel.WILLHABEN
    assert n.price == Decimal("80")


def test_build_sources_respects_toggles():
    # Nothing configured -> no sources.
    assert build_sources(Settings(KLEINANZEIGEN_ENABLED=False)) == []

    # Kleinanzeigen needs both the flag and an actor.
    s = build_sources(
        Settings(KLEINANZEIGEN_ENABLED=True, APIFY_KLEINANZEIGEN_ACTOR="user~ka")
    )
    assert [src.channel for src in s] == [Channel.KLEINANZEIGEN]

    # All three enabled + configured.
    s = build_sources(
        Settings(
            KLEINANZEIGEN_ENABLED=True,
            APIFY_KLEINANZEIGEN_ACTOR="user~ka",
            WILLHABEN_ENABLED=True,
            APIFY_WILLHABEN_ACTOR="user~wh",
            EBAY_BROWSE_ENABLED=True,
            EBAY_CLIENT_ID="cid",
            EBAY_CLIENT_SECRET="sec",
        )
    )
    assert {src.channel for src in s} == {
        Channel.KLEINANZEIGEN,
        Channel.WILLHABEN,
        Channel.EBAY_BROWSE,
    }
