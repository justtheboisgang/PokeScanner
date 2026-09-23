"""Erkennungsquote messen (app.resolverstats)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.clients.tcgdex import TCGdexClient
from app.models.enums import Channel, SellerType
from app.models.listing import Listing
from app.resolverstats import run


@pytest.fixture()
def patched_scope(monkeypatch, scoped_factory):
    monkeypatch.setattr("app.resolverstats.session_scope", scoped_factory)
    return scoped_factory


def _listing(db, title, ext):
    db.add(
        Listing(
            channel=Channel.EBAY_BROWSE,
            external_id=ext,
            title=title,
            price=Decimal("30"),
            currency="EUR",
            seller_type=SellerType.PRIVATE,
            images=[],
        )
    )
    db.flush()
    db.commit()


def _tcgdex(cards):
    return TCGdexClient(
        base_url="https://api.tcgdex.net/v2",
        primary_lang="de",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=cards)),
    )


def test_bundles_do_not_drag_the_rate_down(patched_scope, db, monkeypatch, capsys):
    """Konvolute gehoeren dem Betreiber — sie sind kein Misserfolg der Automatik."""
    _listing(db, "Pokemon Karten Konvolut 50 Stueck", "b1")
    _listing(db, "Pokemon Sammlung Aufloesung", "b2")
    _listing(db, "Glurak Holo 4/102 Base Set Deutsch", "s1")

    monkeypatch.setattr(
        "app.resolverstats.TCGdexClient",
        lambda *a, **kw: _tcgdex([{"id": "base1-4", "localId": "4", "name": "Glurak"}]),
    )
    recognized = run(limit=10)
    out = capsys.readouterr().out

    assert recognized == 1
    assert "Konvolute / Sammlungen :    2" in out
    # Eine Einzelkarte, eine erkannt -> 100%, nicht 33%.
    assert "Einzelkarten           :    1" in out
    assert "(100%)" in out


def test_misses_are_listed_with_their_reason(patched_scope, db, monkeypatch, capsys):
    _listing(db, "Pokemon Karte Glurak Holo Deutsch ohne Nummer", "m1")

    monkeypatch.setattr(
        "app.resolverstats.TCGdexClient", lambda *a, **kw: _tcgdex([])
    )
    recognized = run(limit=10, show_titles=True)
    out = capsys.readouterr().out

    assert recognized == 0
    assert "keine Kartennummer im Titel" in out
    assert "Glurak Holo Deutsch ohne Nummer" in out


def test_reprints_are_counted_separately(patched_scope, db, monkeypatch, capsys):
    """Ein Neudruck ist kein Fehlschlag, sondern eine bewusste Ablehnung."""
    _listing(db, "Pokemon Glurak 4/102 30 Jahre Jubilaeum Deutsch", "r1")

    monkeypatch.setattr(
        "app.resolverstats.TCGdexClient", lambda *a, **kw: _tcgdex([])
    )
    run(limit=10)
    out = capsys.readouterr().out
    assert "Neudrucke / Jubilaeen  :    1" in out
    assert "Einzelkarten           :    0" in out


def test_accessories_are_not_counted_as_unrecognized_cards(patched_scope, db,
                                                           monkeypatch, capsys):
    """Ein Display ist keine Karte — es darf die Quote nicht druecken."""
    _listing(db, "Pokemon Display 36 Booster Karmesin Deutsch OVP", "p1")
    _listing(db, "Pokemon TCG Muenzen mehrfarbig teils Holofolie", "p2")
    _listing(db, "Pokemon Elite Trainer Box Deutsch versiegelt", "p3")
    _listing(db, "Glurak Holo 4/102 Base Set Deutsch", "s1")

    monkeypatch.setattr(
        "app.resolverstats.TCGdexClient",
        lambda *a, **kw: _tcgdex([{"id": "base1-4", "localId": "4", "name": "Glurak"}]),
    )
    run(limit=10)
    out = capsys.readouterr().out

    assert "Zubehoer / versiegelt  :    3" in out
    assert "Einzelkarten           :    1" in out
    assert "(100%)" in out


def test_a_card_number_beats_a_product_word(patched_scope, db, monkeypatch, capsys):
    """'Aus Booster gezogen' macht aus einer Karte kein Zubehoer."""
    _listing(db, "Glurak 4/102 Holo Deutsch aus Booster gezogen", "s2")

    monkeypatch.setattr(
        "app.resolverstats.TCGdexClient",
        lambda *a, **kw: _tcgdex([{"id": "base1-4", "localId": "4", "name": "Glurak"}]),
    )
    recognized = run(limit=10)
    out = capsys.readouterr().out
    assert recognized == 1
    assert "Zubehoer / versiegelt  :    0" in out


def test_hits_can_be_listed_for_a_spot_check(patched_scope, db, monkeypatch, capsys):
    """Die Quote sagt nicht, ob RICHTIG erkannt wurde — dafuer die Trefferliste."""
    _listing(db, "Glurak Holo 4/102 Base Set Deutsch", "h1")

    monkeypatch.setattr(
        "app.resolverstats.TCGdexClient",
        lambda *a, **kw: _tcgdex([{"id": "base1-4", "localId": "4", "name": "Glurak"}]),
    )
    run(limit=10, show_hits=True)
    out = capsys.readouterr().out
    assert "Erkannt als" in out
    assert "Glurak 4/102 [base1-4]" in out
