"""PokeWallet-Client + die Markt-vs-Verkauf-Analyse.

Kernpunkt: PokeWallet liefert ANGEBOTSPREISE, keine echten Verkäufe. Es darf
nur Stufe 4 speisen und wird sonst neben dem Verkaufswert festgehalten, damit
die Lücke messbar wird.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.clients.exceptions import ClientError, RateLimitError
from app.clients.pokewallet import MarketPricing, PokeWalletClient

_RESULT = {
    "id": "pk_abc",
    "card_info": {"name": "Glurak", "set_name": "Basis", "card_number": "4/102"},
    "cardmarket": {
        "prices": [
            {"variant_type": "normal", "avg": 80.0, "low": 60.0, "trend": 85.0,
             "avg7": 82.0, "avg30": 79.0},
            {"variant_type": "holo", "avg": 300.0, "low": 250.0, "trend": 320.0,
             "avg7": 310.0, "avg30": 305.0},
        ]
    },
    "tcgplayer": {
        "prices": [
            {"sub_type_name": "Normal", "market_price": 95.0, "low_price": 70.0},
            {"sub_type_name": "Holofoil", "market_price": 350.0, "low_price": 300.0},
        ]
    },
}


def _client(handler, **kw) -> PokeWalletClient:
    kw.setdefault("min_interval", 0)
    return PokeWalletClient(
        api_key="pk_live_test",
        base_url="https://api.pokewallet.io",
        transport=httpx.MockTransport(handler),
        **kw,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": [_RESULT]})


def test_picks_the_normal_variant_by_default():
    p = _client(_ok).pricing_for("Glurak", "4/102")
    assert p is not None
    assert p.cm_trend == Decimal("85.0")
    assert p.cm_avg7 == Decimal("82.0")
    assert p.variant == "normal"


def test_picks_the_holo_variant_when_asked():
    p = _client(_ok).pricing_for("Glurak", "4/102", prefer_holo=True)
    assert p.cm_trend == Decimal("320.0")
    assert p.variant == "holo"


def test_usd_is_kept_separate_from_eur():
    """TCGPlayer ist USD und darf nie in einen EUR-Wert einfliessen (§6)."""
    p = _client(_ok).pricing_for("Glurak", "4/102")
    assert p.tcg_market_usd == Decimal("95.0")
    # best_eur zieht ausschliesslich Cardmarket-Felder heran.
    assert p.best_eur() == Decimal("82.0")       # avg7 zuerst
    assert p.best_eur() != p.tcg_market_usd


def test_best_eur_prefers_the_seven_day_average():
    m = MarketPricing(cm_trend=Decimal("100"), cm_avg7=Decimal("90"),
                      cm_avg=Decimal("80"))
    assert m.best_eur() == Decimal("90")
    assert MarketPricing(cm_avg=Decimal("80")).best_eur() == Decimal("80")
    assert MarketPricing().best_eur() is None
    assert MarketPricing().has_eur is False


def test_number_is_part_of_the_query():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"results": [_RESULT]})

    _client(handler).pricing_for("Glurak", "4/102")
    assert seen["q"] == "Glurak 4/102"


def test_no_key_means_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called")

    c = PokeWalletClient(api_key="", base_url="https://x",
                         transport=httpx.MockTransport(handler))
    assert c.enabled is False
    assert c.pricing_for("Glurak", "4/102") is None


def test_empty_results_are_not_invented():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    assert _client(handler).pricing_for("Gibtsnicht", "1/1") is None


def test_rate_limit_is_raised_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Rate limit exceeded"})

    with pytest.raises(RateLimitError):
        _client(handler).pricing_for("Glurak", "4/102")


def test_error_body_is_surfaced():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error":"Invalid API key"}')

    with pytest.raises(ClientError) as exc:
        _client(handler).search("glurak")
    assert "Invalid API key" in str(exc.value)


def test_requests_are_spaced_out():
    slept: list[float] = []
    clock = {"t": 0.0}
    c = _client(_ok, min_interval=1.0, sleep=slept.append,
                monotonic=lambda: clock["t"])
    c.pricing_for("Glurak", "4/102")
    assert slept == []
    c.pricing_for("Turtok", "2/102")
    assert slept == [1.0]


def test_remaining_day_is_tracked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_RESULT]},
                              headers={"X-RateLimit-Remaining-Day": "823"})

    c = _client(handler)
    c.pricing_for("Glurak", "4/102")
    assert c.remaining_day == 823


# --- Markt vs. echte Verkaeufe (die eigentliche Kennzahl) ------------------


def _valued_card(db, sold_eur, market_eur, ext, level=1,
                 source=None):
    """Eine Karte mit echtem Verkaufswert UND Marktpreis zum selben Zeitpunkt."""
    from app.models.card import Card, Variant
    from app.models.enums import Condition, Language, Printing, ReferenceSource
    from app.models.market_snapshot import MarketSnapshot
    from app.models.reference_value import ReferenceValue

    card = Card(name=f"Karte {ext}", tcgdex_id=f"base1-{ext}")
    db.add(card)
    db.flush()
    variant = Variant(card_id=card.id, language=Language.DE,
                      condition=Condition.PLAYED, printing=Printing.NORMAL)
    db.add(variant)
    db.flush()
    rv = ReferenceValue(
        variant_id=variant.id,
        value=Decimal(str(sold_eur)),
        currency="EUR",
        source=source or ReferenceSource.SOLDCOMPS,
        cascade_level=level,
        sample_size=7,
        is_weak=False,
    )
    db.add(rv)
    db.flush()
    db.add(MarketSnapshot(
        variant_id=variant.id,
        reference_value_id=rv.id,
        cm_avg7=Decimal(str(market_eur)),
        tcg_market_usd=Decimal("999"),   # USD darf nie einfliessen
    ))
    db.commit()
    return rv


def test_market_comparison_measures_the_gap(client, db):
    # Echte Verkaeufe bei der Haelfte des Marktpreises.
    _valued_card(db, sold_eur=50, market_eur=100, ext="1")
    _valued_card(db, sold_eur=40, market_eur=80, ext="2")
    _valued_card(db, sold_eur=30, market_eur=60, ext="3")

    cmp = client.get("/api/calibration").json()["market_comparison"]
    assert cmp["sample_size"] == 3
    assert cmp["median_ratio"] == pytest.approx(0.5)
    assert cmp["median_sold_eur"] == pytest.approx(40.0)
    assert cmp["median_market_eur"] == pytest.approx(80.0)
    assert "zu hoch" in cmp["verdict"]


def test_stufe_4_values_are_excluded(client, db):
    """Stufe 4 STAMMT aus Marktdaten — sie mit Marktdaten zu vergleichen
    wuerde nur sich selbst messen."""
    from app.models.enums import ReferenceSource

    _valued_card(db, sold_eur=50, market_eur=100, ext="9", level=4,
                 source=ReferenceSource.TCGDEX_CARDMARKET)
    cmp = client.get("/api/calibration").json()["market_comparison"]
    assert cmp["sample_size"] == 0


def test_market_comparison_without_data_says_so(client, db):
    cmp = client.get("/api/calibration").json()["market_comparison"]
    assert cmp["sample_size"] == 0
    assert cmp["median_ratio"] is None
    assert "Noch keine" in cmp["verdict"]
