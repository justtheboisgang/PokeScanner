"""Reference-value cascade (§6) and adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.clients.tcgdex import CardmarketPricing
from app.models.enums import Condition, Language, Printing, ReferenceSource
from app.pricing.adapters import parse_condition, sold_item_to_comp
from app.pricing.cascade import (
    CascadeConfig,
    ReferenceComp,
    select_reference_value,
    within_window,
)

CONFIG = CascadeConfig(
    min_sample_size=5,
    window_days=90,
    condition_factor=Decimal("0.6"),
    language_factor=Decimal("0.8"),
)

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def comp(price, *, language=Language.DE, condition=Condition.PLAYED, sold_days_ago=1):
    return ReferenceComp(
        price=Decimal(str(price)),
        currency="EUR",
        sold_at=NOW - timedelta(days=sold_days_ago),
        language=language,
        condition=condition,
        boa_hydrated=True,
    )


def _select(comps_same, comps_en=None, cardmarket=None, variant_lang=Language.DE,
            variant_cond=Condition.PLAYED, printing=Printing.UNKNOWN):
    return select_reference_value(
        variant_language=variant_lang,
        variant_condition=variant_cond,
        variant_printing=printing,
        comps_same_lang=comps_same,
        comps_english=comps_en or [],
        cardmarket=cardmarket,
        config=CONFIG,
    )


def test_stufe1_matching_condition_uses_median():
    comps = [comp(p, condition=Condition.PLAYED) for p in (10, 20, 30, 40, 50)]
    r = _select(comps)
    assert r.cascade_level == 1
    assert r.value == Decimal("30.00")
    assert r.sample_size == 5
    assert r.source == ReferenceSource.SOLDCOMPS
    assert r.is_weak is False


def test_stufe1_needs_n_matching_condition():
    # Only 4 matching PLAYED -> below N, falls through to Stufe 2 (all conditions).
    comps = [comp(p, condition=Condition.PLAYED) for p in (10, 20, 30, 40)]
    comps += [comp(100, condition=Condition.UNKNOWN)]
    r = _select(comps)
    assert r.cascade_level == 2


def test_stufe2_all_conditions_times_condition_factor():
    comps = [comp(p, condition=Condition.UNKNOWN) for p in (10, 20, 30, 40, 50)]
    r = _select(comps)  # variant condition PLAYED, none match -> Stufe 2
    assert r.cascade_level == 2
    assert r.value == Decimal("18.00")  # median 30 * 0.6
    assert r.sample_size == 5


def test_stufe3_english_times_language_factor():
    en = [comp(p, language=Language.EN, condition=Condition.UNKNOWN)
          for p in (10, 20, 30, 40, 50)]
    r = _select([], comps_en=en)
    assert r.cascade_level == 3
    assert r.value == Decimal("24.00")  # median 30 * 0.8
    assert r.sample_size == 5


def test_english_variant_skips_stufe3():
    # An EN variant has no DE->EN step; with too few comps it must NOT use Stufe 3.
    en = [comp(p, language=Language.EN, condition=Condition.UNKNOWN)
          for p in (10, 20, 30, 40, 50)]
    cm = CardmarketPricing(trend=Decimal("99"))
    r = _select([], comps_en=en, cardmarket=cm, variant_lang=Language.EN)
    assert r.cascade_level == 4  # jumps past 3


def test_stufe4_cardmarket_is_weak():
    cm = CardmarketPricing(trend=Decimal("42.50"), avg7=Decimal("40"))
    r = _select([], cardmarket=cm)
    assert r.cascade_level == 4
    assert r.value == Decimal("42.50")
    assert r.is_weak is True
    assert r.source == ReferenceSource.TCGDEX_CARDMARKET
    assert r.sample_size == 0


def test_stufe4_falls_back_to_avg7_when_no_trend():
    cm = CardmarketPricing(avg7=Decimal("40"))
    r = _select([], cardmarket=cm)
    assert r.value == Decimal("40.00")


def test_stufe4_holo_variant_prefers_holo_price():
    cm = CardmarketPricing(trend=Decimal("40"), trend_holo=Decimal("120"))
    r = _select([], cardmarket=cm, printing=Printing.HOLO)
    assert r.value == Decimal("120.00")


def test_stufe5_unbewertbar():
    r = _select([])
    assert r.cascade_level == 5
    assert r.value is None
    assert r.is_valuable is False
    assert r.source is None


def test_within_window_filters_old_but_keeps_unknown_dates():
    fresh = comp(10, sold_days_ago=10)
    old = comp(20, sold_days_ago=200)
    unknown = ReferenceComp(
        price=Decimal("30"), currency="EUR", sold_at=None,
        language=Language.DE, condition=Condition.PLAYED, boa_hydrated=True,
    )
    kept = within_window([fresh, old, unknown], 90, now=NOW)
    assert fresh in kept
    assert unknown in kept  # R4: kept despite unknown date
    assert old not in kept


# --- adapter ---------------------------------------------------------------

def test_parse_condition_maps_german_and_english():
    assert parse_condition("gespielt") == Condition.PLAYED
    assert parse_condition("Near Mint") == Condition.NEAR_MINT
    assert parse_condition("etwas völlig anderes") == Condition.UNKNOWN
    assert parse_condition(None) == Condition.UNKNOWN


def test_sold_item_to_comp_parses_core_fields():
    item = {
        "itemId": "123",
        "soldPrice": "45.50",
        "soldDate": "2026-09-01T12:00:00Z",
        "boaHydrated": True,
        "epid": 999,
        "itemSpecifics": {"Zustand": "Gespielt"},
    }
    c = sold_item_to_comp(item, language=Language.DE)
    assert c is not None
    assert c.price == Decimal("45.50")
    assert c.boa_hydrated is True
    assert c.condition == Condition.PLAYED
    assert c.epid == "999"
    assert c.source_item_id == "123"
    assert c.sold_at.year == 2026


def test_sold_item_without_price_is_dropped():
    assert sold_item_to_comp({"soldPrice": None}, language=Language.DE) is None
    assert sold_item_to_comp({"soldPrice": 0}, language=Language.DE) is None


# --- Ausfall einer Stufe darf die Kaskade nicht toeten ---------------------


def test_soldcomps_outage_falls_through_to_cardmarket():
    """Faellt SoldComps aus, muss Stufe 4 uebernehmen statt unbewertbar zu sein."""
    from app.clients.tcgdex import CardmarketPricing
    from app.models.card import Card, Variant
    from app.pricing.service import ReferenceValueCascade

    class _BrokenSoldComps:
        request_count = 0

        def scrape_sold(self, *a, **kw):
            raise RuntimeError("SoldComps error 400: bad request")

    class _Tcgdex:
        def get_cardmarket_pricing(self, card_id):
            return CardmarketPricing(trend=Decimal("42.50"))

    card = Card(name="Glurak", number="4/102", tcgdex_id="base1-4")
    variant = Variant(
        card_id=1, language=Language.DE, condition=Condition.PLAYED,
        printing=Printing.NORMAL,
    )
    result = ReferenceValueCascade(_BrokenSoldComps(), _Tcgdex(), CONFIG).compute(
        card, variant
    )
    assert result.cascade_level == 4
    assert result.value == Decimal("42.50")
    assert result.is_weak is True          # ehrlich als schwach markiert
    assert result.source == ReferenceSource.TCGDEX_CARDMARKET


def test_soldcomps_outage_without_cardmarket_is_unbewertbar():
    """Ohne jede Quelle bleibt es unbewertbar — nie geraten."""
    from app.models.card import Card, Variant
    from app.pricing.service import ReferenceValueCascade

    class _BrokenSoldComps:
        def scrape_sold(self, *a, **kw):
            raise RuntimeError("boom")

    class _NoPricing:
        def get_cardmarket_pricing(self, card_id):
            return None

    card = Card(name="Glurak", number="4/102", tcgdex_id="base1-4")
    variant = Variant(card_id=1, language=Language.DE, condition=Condition.PLAYED,
                      printing=Printing.NORMAL)
    result = ReferenceValueCascade(_BrokenSoldComps(), _NoPricing(), CONFIG).compute(
        card, variant
    )
    assert result.cascade_level == 5
    assert result.is_valuable is False
