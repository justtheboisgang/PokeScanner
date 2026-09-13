"""Alarm rule (§7)."""

from __future__ import annotations

from decimal import Decimal

from app.config_data import SearchTerms
from app.ingest.alarm import evaluate
from app.ingest.kleinanzeigen import NormalizedListing
from app.models.enums import SellerType

TERMS = SearchTerms(
    positive=("alte pokemon karten",),
    negative=("repro", "psa", "graded"),
    active=("alte pokemon karten",),
)


def _listing(title="Alte Pokemon Karten", desc="", price=None):
    return NormalizedListing(
        external_id="1",
        title=title,
        description=desc,
        price=(Decimal(str(price)) if price is not None else None),
        currency="EUR",
        location="Berlin",
        seller_type=SellerType.PRIVATE,
        images=[],
        url="https://x",
    )


def test_pass_without_price_by_default():
    d = evaluate(_listing(price=None), search_terms=TERMS)
    assert d.should_alert is True


def test_excluded_by_negative_term():
    d = evaluate(_listing(desc="repro fake"), search_terms=TERMS)
    assert d.should_alert is False
    assert "negative" in d.reason


def test_graded_excluded():
    d = evaluate(_listing(title="Glurak PSA 10"), search_terms=TERMS)
    assert d.should_alert is False


def test_require_price_suppresses_priceless():
    d = evaluate(_listing(price=None), search_terms=TERMS, require_price=True)
    assert d.should_alert is False


def test_price_ceiling_suppresses_expensive():
    d = evaluate(_listing(price=500), search_terms=TERMS, price_ceiling=Decimal("300"))
    assert d.should_alert is False
    d2 = evaluate(_listing(price=200), search_terms=TERMS, price_ceiling=Decimal("300"))
    assert d2.should_alert is True


def test_no_ceiling_lets_expensive_through():
    # R4: großzügig — teure Konvolute sind oft gerade die guten Deals.
    d = evaluate(_listing(price=999), search_terms=TERMS)
    assert d.should_alert is True
