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
    looks_like_reprint,
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


def test_missing_number_and_unknown_set_blocks_resolution():
    """Ohne Nummer wird das Set gesucht — findet sich keins, bleibt es dabei.

    Frueher endete der Resolver hier sofort und ohne jede Anfrage. Seit Titel
    auch ueber den Set-Namen aufgeloest werden, darf er nachsehen — ergebnislos
    heisst aber weiterhin: unbewertbar.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    r = SingleCardTitleResolver(_tcgdex(handler))
    assert r.resolve("Glurak Holo irgendwas", None) is None


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


# --- Nenner der Kartennummer + Neudruck-Sperre ------------------------------

_SETS = [
    {"id": "base1", "cardCount": {"official": 102}},
    {"id": "dp3", "cardCount": {"official": 100}},
    {"id": "pl1", "cardCount": {"official": 127}},
]


def _resolver_with_sets(cards_by_token):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sets"):
            return httpx.Response(200, json=_SETS)
        q = request.url.params.get("name", "").replace("like:", "")
        return httpx.Response(200, json=cards_by_token.get(q, []))

    return SingleCardTitleResolver(_tcgdex(handler))


def test_denominator_narrows_same_numbered_cards():
    """"2/102" heisst: Set mit 102 Karten. Das trennt Base Set von den anderen."""
    r = _resolver_with_sets(
        {"Turtok": [
            {"id": "dp3-2", "name": "Turtok"},
            {"id": "base1-2", "name": "Turtok"},
            {"id": "pl1-2", "name": "Turtok"},
        ]}
    )
    resolved = r.resolve("Turtok 2/102 Rare Holo Deutsch Base Set 1999", None)
    assert resolved is not None
    assert resolved.tcgdex_id == "base1-2"


def test_denominator_that_matches_nothing_stays_unbewertbar():
    r = _resolver_with_sets(
        {"Turtok": [{"id": "dp3-2", "name": "Turtok"}, {"id": "pl1-2", "name": "Turtok"}]}
    )
    # Kein Set mit 999 Karten -> die Mehrdeutigkeit bleibt bestehen.
    assert r.resolve("Turtok 2/999 Deutsch", None) is None


def test_reprints_never_resolve():
    """Neudrucke tragen die Nummern des Originals, sind aber ein Bruchteil wert."""
    r = _resolver_with_sets({"Turtok": [{"id": "base1-2", "name": "Turtok"}]})
    for title in (
        "Turtok 2/102 Rare Holo Deutsch Celebration 25. Jubiläum",
        "Turtok 2/102 Classic Collection",
        "Turtok 2/102 Promo",
        "Turtok 2/102 Neudruck",
    ):
        assert r.resolve(title, None) is None, title
    # Ohne Neudruck-Hinweis loest dieselbe Karte sehr wohl auf.
    assert r.resolve("Turtok 2/102 Base Set 1999 Deutsch", None) is not None


def test_reprint_check_is_not_fooled_by_normal_words():
    assert looks_like_reprint("Glurak 4/102 Base Set Holo Deutsch") is False


# --- Nachschlagschwelle: Budget nicht fuer Cent-Karten verbrennen -----------


def _priced_candidate(db, channel, price, ext):
    lst = Listing(
        channel=channel,
        external_id=ext,
        title="Windhauch 93/102 Base Set Deutsch",
        price=Decimal(price),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    cand = Candidate(listing_id=lst.id, matched_search_term="base set")
    db.add(cand)
    db.flush()
    return cand


def _auto(db, cand):
    resolved = ResolvedCard("base1-93", "Windhauch", "93/102", Language.DE,
                            Printing.NORMAL)
    return auto_value_candidate(
        db,
        cand,
        resolver=_StubResolver(resolved),
        settings=get_settings().model_copy(
            update={"soldcomps_api_key": "sc_test",
                    "single_card_lookup_threshold_eur": Decimal("15")}
        ),
        soldcomps=_soldcomps(),
        tcgdex=_tcgdex(_one_card_handler({})),
    )


def test_cheap_ebay_listing_is_not_looked_up(db):
    """Eine 3-EUR-Trainerkarte auf eBay ist keine 0,04 EUR Abfrage wert."""
    cand = _priced_candidate(db, Channel.EBAY_BROWSE, "3.00", "cheap1")
    result = _auto(db, cand)
    assert result.soldcomps_active is False
    assert "Nachschlagschwelle" in (result.note or "")
    assert cand.reference_value_id is None
    assert db.scalars(select(CandidateCard)).all() == []


def test_expensive_ebay_listing_is_looked_up(db):
    cand = _priced_candidate(db, Channel.EBAY_BROWSE, "80.00", "rich1")
    result = _auto(db, cand)
    assert result.soldcomps_active is True
    assert cand.reference_value_id is not None


def test_threshold_never_blocks_kleinanzeigen(db):
    """Auf Kleinanzeigen IST der niedrige Preis der Werthebel — nie blocken."""
    cand = _priced_candidate(db, Channel.KLEINANZEIGEN, "3.00", "ka_cheap")
    result = _auto(db, cand)
    assert result.soldcomps_active is True
    assert cand.reference_value_id is not None


# --- Sperre schuetzt Handarbeit, nicht eigene Fehlversuche -----------------


def _card_row(db, cand, source):
    from app.models.card import Card, Variant
    from app.models.enums import Condition

    card = Card(name="Alt", tcgdex_id=f"x-{source}-{cand.id}")
    db.add(card)
    db.flush()
    variant = Variant(card_id=card.id, language=Language.DE,
                      condition=Condition.PLAYED, printing=Printing.NORMAL)
    db.add(variant)
    db.flush()
    db.add(CandidateCard(candidate_id=cand.id, variant_id=variant.id,
                         quantity=1, source=source))
    db.flush()
    return variant


def _auto_resolved(db, cand):
    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE,
                            Printing.NORMAL)
    return auto_value_candidate(
        db, cand, resolver=_StubResolver(resolved),
        settings=get_settings().model_copy(
            update={"soldcomps_api_key": "sc_test"}
        ),
        soldcomps=_soldcomps(), tcgdex=_tcgdex(_one_card_handler({})),
    )


def test_manual_identification_is_never_overwritten(db):
    cand = _candidate(db, price="120")
    variant = _card_row(db, cand, "manual")
    result = _auto_resolved(db, cand)
    assert result.soldcomps_active is False
    rows = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].variant_id == variant.id


def test_failed_auto_attempt_is_retried(db):
    """Ein abgebrochener Versuch darf die Karte nicht dauerhaft blockieren."""
    cand = _candidate(db, price="120")
    _card_row(db, cand, "auto")
    result = _auto_resolved(db, cand)
    assert result.soldcomps_active is True
    assert cand.reference_value_id is not None


def test_auto_valuation_marks_its_cards_as_auto(db):
    cand = _candidate(db, price="120")
    _auto_resolved(db, cand)
    rows = db.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == cand.id)
    ).all()
    assert [r.source for r in rows] == ["auto"]


# --- Zweisprachige Suche: englische Titel auf dem deutschen Markt ----------
#
# Sehr viele eBay-Titel tragen den ENGLISCHEN Kartennamen, auch bei deutschen
# und internationalen Verkaeufern ("Growlithe 004/020", "Bulbasaur Base Set").
# Die deutsche TCGdex-Suche findet dafuer nichts — Growlithe heisst dort
# "Fukano" — also blieben all diese Angebote stumm unbewertbar.

_EN_ONLY = {"Bulbasaur": [{"id": "base1-44", "name": "Bulbasaur"}]}
_DE_ONLY = {"Bisasam": [{"id": "base1-44", "name": "Bisasam"}]}


def _bilingual_resolver():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sets"):
            return httpx.Response(200, json=[{"id": "base1",
                                              "cardCount": {"official": 102}}])
        q = request.url.params.get("name", "").replace("like:", "")
        table = _DE_ONLY if "/de/" in request.url.path else _EN_ONLY
        return httpx.Response(200, json=table.get(q, []))

    return SingleCardTitleResolver(_tcgdex(handler))


def test_english_title_resolves_via_english_fallback():
    resolved = _bilingual_resolver().resolve("Bulbasaur 44/102 Base Set NM", None)
    assert resolved is not None
    assert resolved.tcgdex_id == "base1-44"


def test_card_found_only_in_english_counts_as_english():
    """Dass nur die englischen Namen passen, IST der Sprachbeweis."""
    resolved = _bilingual_resolver().resolve("Bulbasaur 44/102 Base Set NM", None)
    assert resolved.language == Language.EN


def test_explicit_german_in_title_beats_the_inference():
    resolved = _bilingual_resolver().resolve(
        "Bulbasaur 44/102 Base Set deutsch NM", None
    )
    assert resolved.language == Language.DE


def test_german_name_still_resolves_without_english_pass():
    calls = {"en": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sets"):
            return httpx.Response(200, json=[{"id": "base1",
                                              "cardCount": {"official": 102}}])
        if "/en/" in request.url.path:
            calls["en"] += 1
        q = request.url.params.get("name", "").replace("like:", "")
        table = _DE_ONLY if "/de/" in request.url.path else _EN_ONLY
        return httpx.Response(200, json=table.get(q, []))

    r = SingleCardTitleResolver(_tcgdex(handler))
    resolved = r.resolve("Bisasam 44/102 Base Set", None)
    assert resolved is not None
    assert resolved.language == Language.DE
    assert calls["en"] == 0  # kein unnoetiger zweiter Durchgang


# --- "unbewertbar" vs. "nie versucht" --------------------------------------
#
# Beides sah im Feed identisch aus. Der Betreiber konnte nicht erkennen, ob die
# Maschine geprueft und nichts gefunden hat oder die Karte nie angefasst wurde —
# und hielt deshalb nie geprueffte Karten fuer wertlos. Jeder Ausgang der
# Automatik haelt seitdem fest, DASS und WARUM.


def test_unresolved_title_records_the_failing_gate(db):
    """Der Grund kommt aus der Spur des Resolvers, nicht aus einer Pauschale."""
    cand = _candidate(db, title="Pokemon Karten Glurak Holo Deutsch")  # keine Nummer
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})

    auto_value_candidate(
        db,
        cand,
        resolver=SingleCardTitleResolver(_tcgdex(_one_card_handler([]))),
        settings=settings,
    )

    assert cand.valuation_attempted_at is not None
    assert "Titel nicht eindeutig" in cand.valuation_note
    assert "Tor 1b" in cand.valuation_note  # fehlende Kartennummer


def test_resolver_without_trace_support_still_gets_marked(db):
    """Das Protokoll verlangt keine Spur — markiert wird trotzdem."""
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})

    auto_value_candidate(db, cand, resolver=NullResolver(), settings=settings)

    assert cand.valuation_attempted_at is not None
    assert "nicht auf genau eine Karte" in cand.valuation_note


def test_below_threshold_says_so_instead_of_staying_silent(db):
    lst = Listing(
        channel=Channel.EBAY_BROWSE,
        external_id="cheap1",
        title="Glurak Holo 4/102",
        price=Decimal("4"),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    cand = Candidate(listing_id=lst.id, matched_search_term="glurak")
    db.add(cand)
    db.flush()
    settings = get_settings().model_copy(
        update={"soldcomps_api_key": "sc_test", "single_card_lookup_threshold_eur": 15}
    )
    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO)

    result = auto_value_candidate(
        db, cand, resolver=_StubResolver(resolved), settings=settings
    )

    assert "Nachschlagschwelle" in result.note
    assert cand.valuation_attempted_at is not None
    assert "Nachschlagschwelle" in cand.valuation_note


def test_missing_key_is_recorded_as_the_reason(db):
    cand = _candidate(db)
    settings = get_settings().model_copy(update={"soldcomps_api_key": ""})
    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO)

    auto_value_candidate(
        db, cand, resolver=_StubResolver(resolved), settings=settings
    )

    assert cand.valuation_attempted_at is not None
    assert "SoldComps" in cand.valuation_note


def test_successful_valuation_clears_a_stale_reason(db):
    cand = _candidate(db, price="120")
    cand.valuation_note = "Titel nicht eindeutig — alter Stand"
    db.flush()
    settings = get_settings().model_copy(update={"soldcomps_api_key": "sc_test"})
    resolved = ResolvedCard("base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO)

    auto_value_candidate(
        db,
        cand,
        resolver=_StubResolver(resolved),
        settings=settings,
        soldcomps=_soldcomps(),
        tcgdex=_tcgdex(_one_card_handler({})),
    )

    assert cand.reference_value_id is not None
    assert cand.valuation_attempted_at is not None
    assert cand.valuation_note is None


# --- Kartennummern jenseits von "4/102" ------------------------------------
#
# Aus dem Live-Feed: Promos, Meisterball-Karten und Trainer-Galerien fielen
# alle durch Tor 1b, weil ihre Nummern ein Buchstabenkuerzel tragen. Das war
# ausgerechnet der wertvolle Teil der Einzelkarten.


def test_extracts_numbers_from_real_ebay_titles():
    from app.pricing.resolver import extract_card_number

    cases = {
        "Kronjuwild WHT 007 MEISTERBALL Weiße Flammen Pokemon DE NM": ("WHT007", None),
        "Glurak G Lv.X DP45 – Pokémon TCG Deutsch Holo SP 120 KP (2009)": ("DP45", None),
        "Pokémon Damythir TG06/TG30 Astral Glanz Trainer Galerie": ("TG06", None),
        "Pokemon Grimmsnarl SV085/SV122 Shiny Vault": ("SV085", None),
        "Pokémon TCG Turtok-EX 009/165 EX Holo Deutsch 330 KP": ("009", 165),
        "Pokemon Karte Glurak Holo 4/102 Base Set Deutsch": ("4", 102),
    }
    for title, (token, size) in cases.items():
        number = extract_card_number(title)
        assert number is not None, title
        assert number.token == token, title
        # Der Nenner zaehlt nur, wenn er wirklich die Set-Groesse ist.
        assert number.set_size == size, title


def test_title_noise_is_not_mistaken_for_a_card_number():
    """Eine nackte Zahl ist keine Kartennummer — sonst wird jeder Titel 'erkannt'."""
    from app.pricing.resolver import extract_card_number

    for title in (
        "Pokemon Karten 30 Jahre Konvolut 31 Karten Pikachu komplett 1 bis 30",
        "826 gemischte japanische Pokemon Karten Konvolut - 86 Rare",
        "Pokemon TCG Ascended Heroes Bulk Bundle - 380+ Karten",
        "Pokemon Karten Ar Konvolut Verkauf",
        "Pokemon Glurak Holo 45 Karten Sammlung",   # "Holo 45" ist kein Code
    ):
        assert extract_card_number(title) is None, title


def test_number_matching_accepts_both_spellings_but_not_backwards():
    """TCGdex fuehrt Promos mal mit, mal ohne Kuerzel — aber nur in eine Richtung."""
    from app.pricing.resolver import numbers_match

    assert numbers_match("TG06", "TG06") is True
    assert numbers_match("6", "TG06") is True        # TCGdex nur die Zahl
    assert numbers_match("007", "WHT007") is True    # fuehrende Nullen egal
    # Umgekehrt NICHT: sonst wuerde "4/102" auf die Trainer-Galerie TG04 passen
    # und einen voellig falschen Wert erfinden.
    assert numbers_match("TG04", "4") is False
    assert numbers_match("SV085", "85") is False
    assert numbers_match("5", "4") is False


def test_promo_number_resolves_end_to_end():
    """Eine Promo ohne Nenner muss bis zur aufgeloesten Karte durchkommen."""
    cards = [
        {"id": "dpp-DP45", "localId": "DP45", "name": "Glurak G Lv.X"},
        {"id": "base1-4", "localId": "4", "name": "Glurak"},
    ]
    resolver = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    trace: list[str] = []
    resolved = resolver.resolve(
        "Glurak G Lv.X DP45 Pokémon TCG Deutsch Holo SP", None, trace=trace
    )
    assert resolved is not None, trace
    assert resolved.tcgdex_id == "dpp-DP45"
    assert resolved.number == "DP45"


def test_ambiguity_is_resolved_when_only_one_name_is_in_the_title():
    """Drei Suchwoerter bringen Nebentreffer — die dürfen den Fund nicht killen."""
    cards = [
        {"id": "base1-4", "localId": "4", "name": "Glurak"},
        {"id": "xy12-4", "localId": "4", "name": "Evolutionsstein"},
    ]
    resolver = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    trace: list[str] = []
    resolved = resolver.resolve("Pokemon Glurak 4/102 Base Set Deutsch", None, trace=trace)
    assert resolved is not None, trace
    assert resolved.tcgdex_id == "base1-4"


def test_ambiguity_stays_ambiguous_when_both_names_fit():
    """Steht keiner oder stehen beide im Titel, bleibt es ehrlich unbewertbar."""
    cards = [
        {"id": "base1-4", "localId": "4", "name": "Glurak"},
        {"id": "xy2-4", "localId": "4", "name": "Bisaflor"},
    ]
    resolver = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    assert resolver.resolve("Pokemon Glurak und Bisaflor 4/102 Deutsch", None) is None


def test_suffixes_do_not_block_the_name_match():
    """eBay schreibt 'Turtok-EX', TCGdex fuehrt 'Turtok ex'."""
    cards = [
        {"id": "sv3-9", "localId": "009", "name": "Turtok ex"},
        {"id": "other-9", "localId": "009", "name": "Wablu"},
    ]
    resolver = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    resolved = resolver.resolve("Pokémon TCG Turtok-EX 009/165 Holo Deutsch", None)
    assert resolved is not None
    assert resolved.tcgdex_id == "sv3-9"


# --- Titel ohne Nummer, aber mit Set-Namen ---------------------------------
#
# Groesste Gruppe der echten Fehlschlaege (aus 300 gemessenen Inseraten):
# "Pokemon Karte Card Kabuto Fossil German Deutsch 1. Edition CGC 8.5".
# Keine Nummer — aber Fossil hat genau ein Kabuto, also ist der Titel genauso
# eindeutig wie mit Nummer.


def _set_handler(sets, cards_by_set):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for set_id, cards in cards_by_set.items():
            if path.endswith(f"/sets/{set_id}"):
                return httpx.Response(200, json={"id": set_id, "cards": cards})
        if path.endswith("/sets"):
            return httpx.Response(200, json=sets)
        return httpx.Response(200, json=[])

    return handler


def test_resolves_by_set_name_when_the_title_has_no_number():
    sets = [{"id": "fossil", "name": "Fossil", "cardCount": {"official": 62}}]
    cards = {
        "fossil": [
            {"id": "fossil-50", "localId": "50", "name": "Kabuto"},
            {"id": "fossil-9", "localId": "9", "name": "Muschas"},
        ]
    }
    r = SingleCardTitleResolver(_tcgdex(_set_handler(sets, cards)))
    trace: list[str] = []
    resolved = r.resolve(
        "Pokemon Karte Card Kabuto Fossil German Deutsch 1. Edition CGC 8.5",
        None,
        trace=trace,
    )
    assert resolved is not None, trace
    assert resolved.tcgdex_id == "fossil-50"
    assert resolved.number == "50"
    assert resolved.language == Language.DE


def test_set_name_path_stays_silent_when_several_cards_fit():
    """Zwei Karten des Sets im Titel -> nicht raten."""
    sets = [{"id": "jungle", "name": "Dschungel", "cardCount": {"official": 64}}]
    cards = {
        "jungle": [
            {"id": "jungle-40", "localId": "40", "name": "Mauzi"},
            {"id": "jungle-26", "localId": "26", "name": "Rizeros"},
        ]
    }
    r = SingleCardTitleResolver(_tcgdex(_set_handler(sets, cards)))
    assert r.resolve("Pokemon Mauzi und Rizeros Dschungel 1. Edition", None) is None


def test_two_set_names_in_one_title_stay_unbewertbar():
    """Echter Titel aus dem Feed: "Expansion Base Set Expedition".

    Base Set ODER Expedition — der Wert unterscheidet sich um ein Vielfaches.
    Genau hier waere ein automatischer Wert erfunden, also: Finger weg.
    """
    sets = [
        {"id": "base1", "name": "Base Set", "cardCount": {"official": 102}},
        {"id": "ecard1", "name": "Expedition", "cardCount": {"official": 165}},
    ]
    cards = {
        "base1": [{"id": "base1-58", "localId": "58", "name": "Ponita"}],
        "ecard1": [{"id": "ecard1-121", "localId": "121", "name": "Ponita"}],
    }
    r = SingleCardTitleResolver(_tcgdex(_set_handler(sets, cards)))
    trace: list[str] = []
    assert r.resolve(
        "Pokemon Karte Card Ponyta Ponita Expansion Base Set Expedition japanese",
        None,
        trace=trace,
    ) is None
    assert any("mehrere Sets" in line for line in trace), trace


def test_a_longer_set_name_absorbs_the_shorter_one():
    """"Expedition Base Set" enthaelt "Base Set" — das ist EIN Set, nicht zwei."""
    sets = [
        {"id": "base1", "name": "Base Set", "cardCount": {"official": 102}},
        {"id": "ecard1", "name": "Expedition Base Set", "cardCount": {"official": 165}},
    ]
    cards = {
        "base1": [{"id": "base1-58", "localId": "58", "name": "Ponita"}],
        "ecard1": [{"id": "ecard1-121", "localId": "121", "name": "Ponita"}],
    }
    r = SingleCardTitleResolver(_tcgdex(_set_handler(sets, cards)))
    resolved = r.resolve("Pokemon Karte Ponita Expedition Base Set japanese", None)
    assert resolved is not None
    assert resolved.tcgdex_id == "ecard1-121"


# --- Was gar keine Karte ist ------------------------------------------------


def test_accessories_and_sealed_products_are_recognized():
    """Echte Titel aus dem Feed, die keine Einzelkarte sind."""
    from app.pricing.resolver import looks_like_sealed_product

    for title in (
        "Pokemon Strahlende Funken Sealed Box",
        "Pokémon TCG Champion's Path Elite Trainer Box Charizard Sealed 2020",
        "Pokémon unvollständig Top-Trainer-Box Mega-Entwicklung Fatale Flammen DE",
        "Pokemon Teppich 80cm Turtok Pikachu Anime Manga Gamer Deko",
        "Pokémon Trinkflasche Wasserflasche mit Strohhalm Kinder Pikachu 420ml",
        "Pokemon Metallkarte | Psiana- Gold Optik",
        "Pokemon Mega Charizard UPC Ultra Premium Collection OVP Acryl Case",
        "Pokemon Karten Ectoplasma Gengar zur Auswahl / DE KR JP EN",
        "Pokemon Karten Set 50 Offiziell Neu",
        "Pokémon Battle Ready Deluxe Action Figuren Spielset Pikachu",
    ):
        assert looks_like_sealed_product(title) is True, title


def test_real_cards_are_not_mistaken_for_products():
    from app.pricing.resolver import looks_like_bundle, looks_like_sealed_product

    for title in (
        "Pokemon Karte Card Kabuto Fossil German Deutsch 1. Edition CGC 8.5",
        "Pokemon Karte Card Mauzi Meowth Jungle Dschungel Deutsch 1. Edition",
        "Pokémon TCG M Glurak EX Holo Deutsch 220 KP MEGA EX Sammelkarte",
        "POKEMON EVOLUTIONS MEGA VENUSAUR BISAFLOR EX BECKETT 9 MINT",
    ):
        assert looks_like_bundle(title) is False, title
        assert looks_like_sealed_product(title) is False, title


def test_a_card_number_outranks_a_product_word():
    """"Aus Booster gezogen" bleibt eine Karte — die Nummer entscheidet."""
    cards = [{"id": "base1-4", "localId": "4", "name": "Glurak"}]
    r = SingleCardTitleResolver(_tcgdex(_one_card_handler(cards)))
    assert r.resolve("Glurak 4/102 Holo Deutsch aus Booster gezogen", None) is not None
