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
from app.pricing.resolver import (
    NullResolver,
    ResolvedCard,
    SingleCardTitleResolver,
    card_local_id,
    looks_like_bundle,
    normalize_number,
)


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


# --- Echte eBay-Titel (Regression) -----------------------------------------
#
# Beim ersten Live-Lauf blieben ALLE eBay-Einzelkarten unbewertbar. Drei Fehler:
#   1. "sammel" sperrte "Sammelkarte" — das deutsche Wort fuer EINE Karte.
#   2. Der Abgleich hing allein an localId; fehlt es in der Kurzantwort, passte
#      nie etwas.
#   3. Fuellwoerter wie "Sammelkarte"/"TCG" verdraengten als laengere Tokens den
#      echten Kartennamen aus der Suche.


_REAL_CARDS = {
    "Starmie": [{"id": "base1-64", "name": "Starmie"}],
    "Arktos": [{"id": "fossil1-2", "name": "Arktos"}],
    "Schiggy": [{"id": "base1-63", "name": "Schiggy"}],
    "Raichu": [{"id": "base1-14", "name": "Raichu"},
               {"id": "fossil1-29", "name": "Raichu"}],
}


def _real_resolver():
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("name", "").replace("like:", "")
        # Absichtlich OHNE localId — genau die Antwortform, die alles brach.
        return httpx.Response(200, json=_REAL_CARDS.get(q, []))

    return SingleCardTitleResolver(_tcgdex(handler))


def test_real_ebay_single_card_titles_resolve():
    r = _real_resolver()
    cases = [
        ("Starmie 64/102 Base Set 1. Edition 1st Ed Deutsch Pokemon Sammelkarte TCG",
         "base1-64"),
        ("Pokemon Karte Arktos 2/62 1. Edition Holo Base Set Fossil Rare Deutsch",
         "fossil1-2"),
        ("Schiggy - 1. Edition - Base Set - 63/102 - Pokemon Karte - Deutsch",
         "base1-63"),
        ("Raichu - 1. Edition - Fossil - 29/62 - Pokemon Karte - Deutsch",
         "fossil1-29"),
    ]
    for title, expected in cases:
        resolved = r.resolve(title, None)
        assert resolved is not None, f"blieb unbewertbar: {title}"
        assert resolved.tcgdex_id == expected, title


def test_sammelkarte_is_not_a_bundle():
    """'Sammelkarte' heisst EINE Karte — das darf nie als Konvolut gelten."""
    assert looks_like_bundle("Starmie 64/102 Deutsch Pokemon Sammelkarte") is False
    assert looks_like_bundle("Pokemon Sammelkartenspiel Base Set") is False


def test_real_bundles_are_still_blocked():
    for title in (
        "160 Vintage Pokemon Karten Sammlung Deutsch mit Holo & 1. Edition",
        "Komplette PKM TCG WOTC Team Rocket Pokémon-Kartensammlung der 1. Edition",
        "Pokémon Sammelkartenspiel Base Set 20 Karten Lot Deutsch WotC",
        "10x Pokémon Karte 1st Edition Paket WOTC Base Set Neo Deutsch",
    ):
        assert looks_like_bundle(title) is True, title


def test_local_id_falls_back_to_the_card_id():
    """Ohne diesen Rueckfall loest nichts auf, wenn TCGdex localId weglaesst."""
    assert card_local_id({"id": "base1-63"}) == "63"
    assert card_local_id({"id": "base1-63", "localId": "63"}) == "63"
    assert card_local_id({"id": "nodash"}) is None


def test_card_numbers_compare_without_leading_zeros():
    assert normalize_number("002") == normalize_number("2")
    assert normalize_number("SWSH001") == "swsh001"
