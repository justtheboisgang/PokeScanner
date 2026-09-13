"""Kleinanzeigen normalization + price parsing (§4.4)."""

from __future__ import annotations

from decimal import Decimal

from app.ingest.kleinanzeigen import (
    normalize,
    normalize_lexis_item,
    parse_price,
    parse_seller_type,
)
from app.models.enums import Channel, SellerType


def test_parse_price_variants():
    assert parse_price("50 €") == Decimal("50")
    assert parse_price("50 € VB") == Decimal("50")
    assert parse_price("1.234 €") == Decimal("1234")
    assert parse_price("1.234,50 €") == Decimal("1234.50")
    assert parse_price(80) == Decimal("80")
    assert parse_price("Zu verschenken") == Decimal("0")
    assert parse_price("VB") is None
    assert parse_price("Auf Anfrage") is None
    assert parse_price("") is None
    assert parse_price(None) is None


def test_parse_seller_type():
    assert parse_seller_type("privat") == SellerType.PRIVATE
    assert parse_seller_type("gewerblich") == SellerType.COMMERCIAL
    assert parse_seller_type(True) == SellerType.COMMERCIAL
    assert parse_seller_type(False) == SellerType.PRIVATE
    assert parse_seller_type(None) == SellerType.UNKNOWN


def test_normalize_maps_fields_defensively():
    item = {
        "adId": "abc123",
        "title": "Alte Pokemon Karten Sammlung Dachboden",
        "description": "Konvolut, keine Ahnung was wert",
        "price": "VB",
        "location": "12345 Berlin",
        "url": "https://kleinanzeigen.de/s-anzeige/abc123",
        "images": ["https://img/1.jpg", {"url": "https://img/2.jpg"}],
        "sellerType": "privat",
    }
    n = normalize(item)
    assert n is not None
    assert n.external_id == "abc123"
    assert n.price is None  # VB
    assert n.images == ["https://img/1.jpg", "https://img/2.jpg"]
    assert n.seller_type == SellerType.PRIVATE
    assert n.raw_payload is item  # full raw kept


def test_normalize_falls_back_to_url_as_id():
    item = {"title": "x", "url": "https://kleinanzeigen.de/x"}
    n = normalize(item)
    assert n is not None
    assert n.external_id == "https://kleinanzeigen.de/x"


def test_normalize_returns_none_without_id_or_title():
    assert normalize({"title": "x"}) is None  # no id, no url
    assert normalize({"adId": "1"}) is None  # no title


def test_normalize_lexis_item():
    item = {
        "id": "2910159582",
        "url": "https://kleinanzeigen.de/s-anzeige/x/2910159582-154-19706",
        "title": "Alte Pokemon Karten Sammlung",
        "price": "59.00",  # English decimal — must NOT become 5900
        "priceCurrency": "EUR",
        "address": "10115 Berlin",
        "descriptionText": "Vom Dachboden, ein Knick",
        "primaryImageURL": "https://img/p.jpg",
        "imageURLs": ["https://img/p.jpg", "https://img/2.jpg"],
    }
    n = normalize_lexis_item(item)
    assert n is not None
    assert n.channel == Channel.KLEINANZEIGEN
    assert n.external_id == "2910159582"
    assert n.price == Decimal("59.00")
    assert n.location == "10115 Berlin"
    assert n.images == ["https://img/p.jpg", "https://img/2.jpg"]  # deduped
    assert n.seller_type == SellerType.PRIVATE


def test_normalize_lexis_commercial_when_company_info():
    item = {"id": "1", "title": "x", "price": "10.00", "companyInfo": {"companyName": "GmbH"}}
    assert normalize_lexis_item(item).seller_type == SellerType.COMMERCIAL


def test_normalize_lexis_requires_id_and_title():
    assert normalize_lexis_item({"title": "x"}) is None
    assert normalize_lexis_item({"id": "1"}) is None
