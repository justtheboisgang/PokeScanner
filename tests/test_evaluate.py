"""Manual evaluation trigger (Block 2.3): cascade wiring + candidate_card.

The operator identifies the cards inside a listing (a Konvolut can hold several);
the machine runs the reference-value cascade per card under the cost guard, links
the values, and computes the listing total + estimated profit. Without a SoldComps
key the cards are still stored, but left unbewertbar (R3 honesty).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.clients.soldcomps import SoldCompsClient
from app.clients.tcgdex import TCGdexClient
from app.config import get_settings
from app.models.api_cost import ApiCost
from app.models.candidate import Candidate
from app.models.candidate_card import CandidateCard
from app.models.enums import Condition, Language, Printing, SellerType, Channel
from app.models.listing import Listing
from app.pricing.evaluate import CardEntry, evaluate_candidate


def _sold_items(n: int = 5) -> list[dict]:
    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    return [
        {
            "itemId": f"i{i}",
            "soldPrice": str(price),
            "soldDate": recent,
            "boaHydrated": True,
            "itemSpecifics": {"Zustand": "Gespielt"},
        }
        for i, price in enumerate((10, 20, 30, 40, 50)[:n])
    ]


def _soldcomps() -> SoldCompsClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": _sold_items(), "hasNextPage": False})

    return SoldCompsClient(
        api_key="sc_test",
        base_url="https://api.sold-comps.com",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )


def _tcgdex() -> TCGdexClient:
    # Cards carry no tcgdex_id in these tests, so cardmarket is never fetched;
    # a mock transport just guarantees no accidental live call.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    return TCGdexClient(
        base_url="https://api.tcgdex.net/v2",
        primary_lang="de",
        transport=httpx.MockTransport(handler),
    )


def _candidate(db, price="60") -> Candidate:
    lst = Listing(
        channel=Channel.KLEINANZEIGEN,
        external_id="ev1",
        title="Konvolut alte Pokemon Karten",
        price=Decimal(price),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    cand = Candidate(listing_id=lst.id, matched_search_term="alte pokemon karten")
    db.add(cand)
    db.flush()
    return cand


def test_evaluate_runs_cascade_links_value_and_profit(db):
    cand = _candidate(db, price="60")
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})

    result = evaluate_candidate(
        db,
        cand,
        [
            CardEntry(
                tcgdex_id=None,
                name="Glurak",
                set=None,
                number="4",
                language=Language.DE,
                condition=Condition.PLAYED,
                printing=Printing.NORMAL,
                quantity=1,
            )
        ],
        settings=settings,
        soldcomps=_soldcomps(),
        tcgdex=_tcgdex(),
    )

    assert result.soldcomps_active is True
    assert result.note is None
    # Stufe 1 median of (10,20,30,40,50) = 30.
    assert result.total_value_eur == Decimal("30.00")
    # 30 reference - 60 listing = -30.
    assert result.estimated_profit_eur == Decimal("-30.00")

    cards = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(cards) == 1
    assert cards[0].reference_value_id is not None
    assert cand.estimated_profit == Decimal("-30.00")

    # Cost recorded under the guard (2 scrape requests: DE + EN bucket).
    costs = db.scalars(
        select(ApiCost).where(ApiCost.provider == "soldcomps")
    ).all()
    assert sum(c.units for c in costs) == 2
    assert sum((c.estimated_cost_eur for c in costs), Decimal("0")) > 0


def test_evaluate_konvolut_sums_multiple_cards(db):
    cand = _candidate(db, price="50")
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})

    result = evaluate_candidate(
        db,
        cand,
        [
            CardEntry(None, "Glurak", None, "4", Language.DE, Condition.PLAYED,
                      Printing.NORMAL, 1),
            CardEntry(None, "Bisaflor", None, "15", Language.DE, Condition.PLAYED,
                      Printing.NORMAL, 2),
        ],
        settings=settings,
        soldcomps=_soldcomps(),
        tcgdex=_tcgdex(),
    )

    # 30 (Glurak x1) + 30*2 (Bisaflor x2) = 90.
    assert result.total_value_eur == Decimal("90.00")
    assert result.estimated_profit_eur == Decimal("40.00")
    cards = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(cards) == 2


def test_evaluate_reevaluation_replaces_previous_cards(db):
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})
    entry = CardEntry(None, "Glurak", None, "4", Language.DE, Condition.PLAYED,
                      Printing.NORMAL, 1)

    evaluate_candidate(db, cand, [entry], settings=settings,
                       soldcomps=_soldcomps(), tcgdex=_tcgdex())
    evaluate_candidate(db, cand, [entry], settings=settings,
                       soldcomps=_soldcomps(), tcgdex=_tcgdex())

    cards = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(cards) == 1  # not doubled


def test_evaluate_without_key_stores_cards_unbewertbar(db):
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": ""})

    result = evaluate_candidate(
        db,
        cand,
        [CardEntry(None, "Glurak", None, "4", Language.DE, Condition.PLAYED,
                   Printing.NORMAL, 1)],
        settings=settings,
    )

    assert result.soldcomps_active is False
    assert result.total_value_eur is None
    assert result.note is not None
    cards = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(cards) == 1
    assert cards[0].reference_value_id is None
    # No cost recorded when the provider never runs.
    costs = db.scalars(select(ApiCost)).all()
    assert costs == []


# --- TCGdex autocomplete (Block 2.3 card entry) ----------------------------


def test_search_cards_returns_brief_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("name") == "like:glur"
        return httpx.Response(
            200,
            json=[
                {"id": "base1-4", "name": "Glurak", "image": "https://x/base1-4"},
                {"id": "base2-4", "name": "Glurak", "image": "https://y/base2-4"},
            ],
        )

    client = TCGdexClient(
        base_url="https://api.tcgdex.net/v2",
        primary_lang="de",
        transport=httpx.MockTransport(handler),
    )
    out = client.search_cards("glur", "de")
    assert [c["id"] for c in out] == ["base1-4", "base2-4"]


def test_search_cards_empty_query_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called")

    client = TCGdexClient(
        base_url="https://api.tcgdex.net/v2",
        primary_lang="de",
        transport=httpx.MockTransport(handler),
    )
    assert client.search_cards("  ", "de") == []


# --- HTTP endpoint (unbewertbar path, no live network) ---------------------


def test_evaluate_endpoint_without_key(client, db):
    cand = _candidate(db)
    resp = client.post(
        f"/api/candidates/{cand.id}/evaluate",
        json={
            "cards": [
                {
                    "name": "Glurak",
                    "number": "4",
                    "language": "de",
                    "condition": "played",
                    "printing": "normal",
                    "quantity": 1,
                }
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["soldcomps_active"] is False
    assert body["note"]

    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert len(detail["cards"]) == 1
    assert detail["cards"][0]["name"] == "Glurak"
    assert detail["cards"][0]["reference_value"] is None


def test_manual_evaluation_records_that_it_ran(db):
    """Auch die Handbewertung haelt fest, dass geprueft wurde.

    Ohne Schluessel werden die Karten erfasst, aber nicht bewertet — der Grund
    steht danach am Kandidaten, statt dass der Feed stumm "unbewertbar" sagt.
    """
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": ""})

    result = evaluate_candidate(
        db,
        cand,
        [
            CardEntry(
                tcgdex_id=None,
                name="Glurak",
                set="Base",
                number="4/102",
                language=Language.DE,
                condition=Condition.PLAYED,
                printing=Printing.HOLO,
            )
        ],
        settings=settings,
    )

    assert result.total_value_eur is None
    assert cand.valuation_attempted_at is not None
    assert "SoldComps" in cand.valuation_note
