"""Nachbewertung bestehender Kandidaten (app.revalue)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.candidate import Candidate
from app.models.enums import Channel, SellerType
from app.models.listing import Listing
from app.revalue import run


@pytest.fixture()
def patched_scope(monkeypatch, scoped_factory):
    """run() nutzt session_scope; im Test auf die Testdatenbank umbiegen."""
    monkeypatch.setattr("app.revalue.session_scope", scoped_factory)
    return scoped_factory


def _candidate(db, title, price="50", ext="rv1"):
    lst = Listing(
        channel=Channel.EBAY_BROWSE,
        external_id=ext,
        title=title,
        price=Decimal(price),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    cand = Candidate(listing_id=lst.id, matched_search_term="glurak holo")
    db.add(cand)
    db.flush()
    db.commit()
    return cand


def test_dry_run_costs_nothing_but_records_the_reason(patched_scope, db, monkeypatch,
                                                      capsys):
    """Der Trockenlauf gibt kein Geld aus — haelt den Grund aber fest.

    Aufloesen kostet nichts, also darf der Grund in die Datenbank: danach
    erklaert der Feed bei jeder Karte selbst, warum sie unbewertbar ist.
    """
    cand = _candidate(db, "Glurak Holo 4/102 Base Set Deutsch")

    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("darf im Trockenlauf nicht aufgerufen werden")

    monkeypatch.setattr("app.revalue.auto_value_candidate", _boom)
    monkeypatch.setattr(
        "app.revalue.SingleCardTitleResolver.resolve",
        lambda self, t, d, trace=None: None,
    )
    run(limit=5, dry_run=True)
    out = capsys.readouterr().out
    assert "Trockenlauf" in out
    assert "nicht auflösbar" in out
    db.expire_all()
    cand = db.get(Candidate, cand.id)
    assert cand.reference_value_id is None  # bewertet wurde nichts
    assert cand.valuation_attempted_at is not None
    assert "Titel nicht eindeutig" in cand.valuation_note


def test_reports_when_nothing_is_left_to_value(patched_scope, db, capsys):
    run(limit=5)
    assert "Keine unbewerteten Kandidaten" in capsys.readouterr().out


def test_only_untouched_candidates_are_picked_up(patched_scope, db, monkeypatch,
                                                 capsys):
    """Wer schon einen Referenzwert hat, wird nicht erneut bezahlt."""
    from app.models.card import Card, Variant
    from app.models.enums import Condition, Language, Printing, ReferenceSource
    from app.models.reference_value import ReferenceValue

    card = Card(name="Glurak", tcgdex_id="base1-4")
    db.add(card)
    db.flush()
    variant = Variant(card_id=card.id, language=Language.DE,
                      condition=Condition.PLAYED, printing=Printing.NORMAL)
    db.add(variant)
    db.flush()
    rv = ReferenceValue(variant_id=variant.id, value=Decimal("100"), currency="EUR",
                        source=ReferenceSource.SOLDCOMPS, cascade_level=1,
                        sample_size=6, is_weak=False)
    db.add(rv)
    db.flush()

    done = _candidate(db, "Schon bewertet 4/102", ext="done")
    done.reference_value_id = rv.id
    db.commit()

    seen: list[str] = []

    def _fake(session, cand, **kw):
        from app.pricing.evaluate import EvaluationResult
        seen.append(cand.listing.title)
        return EvaluationResult(None, None, False, "Testlauf")

    # Die Vorauswahl loest vorab auf (gratis) — im Test immer erfolgreich.
    from app.models.enums import Language, Printing
    from app.pricing.resolver import ResolvedCard

    monkeypatch.setattr(
        "app.revalue.SingleCardTitleResolver.resolve",
        lambda self, t, d, trace=None: ResolvedCard("base1-4", "Glurak", "4/102",
                                                    Language.DE, Printing.NORMAL),
    )
    monkeypatch.setattr("app.revalue.auto_value_candidate", _fake)
    _candidate(db, "Noch offen 7/102", ext="open")

    run(limit=10)
    assert seen == ["Noch offen 7/102"]
    assert "Schon bewertet" not in capsys.readouterr().out


def test_limit_counts_real_valuations_not_attempts(patched_scope, db, monkeypatch,
                                                   capsys):
    """Das Limit darf nicht an unauflösbaren Kandidaten verpuffen.

    Beim ersten Live-Lauf waren die fünf neuesten ausgerechnet die
    unauflösbaren — das Limit war weg, bevor eine einzige Karte bewertet wurde.
    """
    from app.models.enums import Language, Printing
    from app.pricing.evaluate import EvaluationResult
    from app.pricing.resolver import ResolvedCard

    # Drei unauflösbare oben, danach zwei auflösbare.
    for i, title in enumerate(["Konvolut A", "Konvolut B", "Konvolut C"]):
        _candidate(db, title, ext=f"no{i}")
    for i, title in enumerate(["Evoli 51/64", "Rattikarl 40/102"]):
        _candidate(db, title, ext=f"yes{i}")

    def _resolve(self, title, description, trace=None):
        if "/" not in title:
            return None
        return ResolvedCard("base1-4", "X", "4/102", Language.DE, Printing.NORMAL)

    valued: list[str] = []

    def _fake(session, cand, **kw):
        valued.append(cand.listing.title)
        return EvaluationResult(None, None, False, None)

    monkeypatch.setattr("app.revalue.SingleCardTitleResolver.resolve", _resolve)
    monkeypatch.setattr("app.revalue.auto_value_candidate", _fake)

    run(limit=2)
    # Beide auflösbaren, keiner der Konvolute.
    assert sorted(valued) == ["Evoli 51/64", "Rattikarl 40/102"]


def test_says_so_when_nothing_in_the_pool_resolves(patched_scope, db, monkeypatch,
                                                  capsys):
    _candidate(db, "Konvolut ohne Nummer", ext="none1")
    monkeypatch.setattr(
        "app.revalue.SingleCardTitleResolver.resolve",
        lambda self, t, d, trace=None: None,
    )
    monkeypatch.setattr(
        "app.revalue.auto_value_candidate",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("darf nicht laufen")),
    )
    run(limit=5)
    assert "Kein auflösbarer Kandidat" in capsys.readouterr().out
