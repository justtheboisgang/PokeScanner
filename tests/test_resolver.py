"""Automatic single-card title resolver + two-gate auto valuation (Block 2.2).

Precision over recall: only titles that unambiguously name ONE card resolve;
Konvolute and vague titles stay unbewertbar (R3).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.clients.tcgdex import TCGdexClient
from app.config import get_settings
from app.models.candidate import Candidate
from app.models.candidate_card import CandidateCard
from app.models.enums import Channel, Language, Printing, SellerType
from app.models.listing import Listing
from app.pricing.evaluate import auto_value_candidate
from app.pricing.resolver import NullResolver, ResolvedCard, SingleCardTitleResolver


def _tcgdex(handler) -> TCGdexClient:
    return TCGdexClient(
        base_url="https://api.tcgdex.net/v2",
        primary_lang="de",
        transport=httpx.MockTransport(handler),
    )


def _one_card_handler(cards):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cards)

    return handler


# --- resolver gates --------------------------------------------------------


def test_null_resolver_never_resolves():
    assert NullResolver().resolve("Glurak 4/102 Holo", None) is None


def test_resolves_unambiguous_single_card():
    cards = [
        {"id": "base1-4", "localId": "4", "name": "Glurak", "image": "x"},
        {"id": "base2-4", "localId": "4", "name": "Glurak", "image": "y"},
    ]
    # Two different sets both have localId 4 -> ambiguous unless the name token
    # narrows to one. Here both are "Glurak" localId 4 -> still two ids -> None.
    r = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    assert r.resolve("Glurak Holo 4/102", None) is None


def test_resolves_when_exactly_one_localid_matches():
    cards = [
        {"id": "base1-4", "localId": "4", "name": "Glurak", "image": "x"},
        {"id": "base1-9", "localId": "9", "name": "Glurak?", "image": "z"},
    ]
    r = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    resolved = r.resolve("Glurak Holo 4/102", None)
    assert resolved is not None
    assert resolved.tcgdex_id == "base1-4"
    assert resolved.number == "4/102"
    assert resolved.printing == Printing.HOLO
    assert resolved.language == Language.DE


def test_bundle_keyword_blocks_resolution():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        called["n"] += 1
        return httpx.Response(200, json=[])

    r = SingleCardTitleResolver(_tcgdex(handler))
    assert r.resolve("Konvolut Pokemon Karten Glurak 4/102", None) is None
    assert called["n"] == 0  # short-circuits before any TCGdex call


def test_missing_number_blocks_resolution():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        called["n"] += 1
        return httpx.Response(200, json=[])

    r = SingleCardTitleResolver(_tcgdex(handler))
    assert r.resolve("Glurak Holo Base Set", None) is None
    assert called["n"] == 0


def test_english_and_first_edition_flags():
    cards = [{"id": "base1-4", "localId": "4", "name": "Charizard"}]
    r = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    resolved = r.resolve("Charizard 4/102 1st Edition english", None)
    assert resolved is not None
    assert resolved.language == Language.EN
    assert resolved.printing == Printing.FIRST_EDITION


# --- two-gate auto valuation ----------------------------------------------


def _sold_items():
    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    return [
        {
            "itemId": f"i{i}",
            "soldPrice": str(p),
            "soldDate": recent,
            "boaHydrated": True,
            "itemSpecifics": {"Zustand": "Gespielt"},
        }
        for i, p in enumerate((100, 200, 300, 400, 500))
    ]


def _soldcomps():
    from app.clients.soldcomps import SoldCompsClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": _sold_items(), "hasNextPage": False})

    return SoldCompsClient(
        api_key="sc_test",
        base_url="https://api.sold-comps.com",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )


class _StubResolver:
    def __init__(self, resolved):
        self._resolved = resolved

    def resolve(self, title, description):
        return self._resolved


def _candidate(db, title="Glurak Holo 4/102", price="120"):
    lst = Listing(
        channel=Channel.KLEINANZEIGEN,
        external_id="auto1",
        title=title,
        price=Decimal(price),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    cand = Candidate(listing_id=lst.id, matched_search_term="glurak")
    db.add(cand)
    db.flush()
    return cand


def test_auto_value_values_resolved_single_card(db):
    cand = _candidate(db, price="120")
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})
    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO)

    result = auto_value_candidate(
        db,
        cand,
        resolver=_StubResolver(resolved),
        settings=settings,
        soldcomps=_soldcomps(),
        tcgdex=_tcgdex(_one_card_handler({})),
    )

    assert result.soldcomps_active is True
    # median(100..500) = 300 (Stufe 1, condition PLAYED comps vs UNKNOWN variant
    # falls to Stufe 2 * 0.70 = 210).
    assert result.total_value_eur == Decimal("210.00")
    assert cand.reference_value_id is not None
    assert cand.estimated_profit == Decimal("90.00")  # 210 - 120
    cards = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(cards) == 1


def test_auto_value_skips_when_unresolved(db):
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})

    result = auto_value_candidate(
        db, cand, resolver=NullResolver(), settings=settings
    )
    assert result.soldcomps_active is False
    assert cand.reference_value_id is None
    cards = db.scalars(select(CandidateCard)).all()
    assert cards == []


def test_auto_value_skips_when_no_key(db):
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": ""})
    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO)

    result = auto_value_candidate(
        db, cand, resolver=_StubResolver(resolved), settings=settings
    )
    # Gate 1 passed but Gate 2 fails: no spend, nothing stored, stays unbewertbar.
    assert result.soldcomps_active is False
    assert cand.reference_value_id is None
    assert db.scalars(select(CandidateCard)).all() == []


def test_auto_value_respects_existing_manual_cards(db):
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})
    # Pretend the operator already identified a card.
    from app.models.card import Card, Variant
    from app.models.enums import Condition

    card = Card(name="Bisaflor", tcgdex_id=None)
    db.add(card)
    db.flush()
    variant = Variant(
        card_id=card.id,
        language=Language.DE,
        condition=Condition.PLAYED,
        printing=Printing.NORMAL,
    )
    db.add(variant)
    db.flush()
    db.add(CandidateCard(candidate_id=cand.id, variant_id=variant.id, quantity=1))
    db.flush()

    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO)
    result = auto_value_candidate(
        db, cand, resolver=_StubResolver(resolved), settings=settings,
        soldcomps=_soldcomps(), tcgdex=_tcgdex(_one_card_handler({})),
    )
    # Manual identification is untouched; auto valuation stands down.
    assert result.soldcomps_active is False
    cards = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(cards) == 1
    assert cards[0].variant_id == variant.id
