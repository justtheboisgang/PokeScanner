"""Auktions-Wache: kurz vor Schluss melden, wenn das Gebot weit unter Wert ist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.auctions import AuctionWatcher
from app.clients.pokewallet import MarketPricing
from app.config import get_settings
from app.models.auction_watch import AuctionWatch
from app.pricing.resolver import ResolvedCard

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


class _Notifier:
    def __init__(self):
        self.sent = []

    @property
    def enabled(self):
        return True

    def send(self, content):
        self.sent.append(content)
        return "msg-1"


class _Resolver:
    def __init__(self, resolved=None):
        self.resolved = resolved

    def resolve(self, title, description, trace=None):
        return self.resolved


class _Wallet:
    enabled = True

    def __init__(self, eur):
        self.eur = eur

    def pricing_for(self, name, number, prefer_holo=False):
        return MarketPricing(cm_avg7=self.eur, card_name=name)


class _Ebay:
    """Ein eBay, das eine Auktion liefert und ihren Gebotsstand fortschreibt."""

    def __init__(self, items, item_price=None):
        self.items = items
        self.item_price = item_price
        self.searched = []

    def search_auctions(self, query, *, ending_within_minutes, limit=50, now=None):
        self.searched.append((query, ending_within_minutes))
        return list(self.items)

    def get_item(self, item_id):
        if self.item_price is None:
            return None
        return {"itemId": item_id, "currentBidPrice": {"value": str(self.item_price),
                                                       "currency": "EUR"}}


def _auction(ext="v1|1|0", price="10.00", minutes=30, title="Glurak 4/102 Holo Deutsch"):
    return {
        "itemId": ext,
        "title": title,
        "currentBidPrice": {"value": price, "currency": "EUR"},
        "itemEndDate": (NOW + timedelta(minutes=minutes)).isoformat().replace(
            "+00:00", "Z"
        ),
        "itemWebUrl": f"https://ebay.de/itm/{ext}",
        "image": {"imageUrl": "https://img/1.jpg"},
    }


@pytest.fixture()
def watcher_factory(scoped_factory, monkeypatch):
    def make(ebay, wallet=None, resolved=None, notifier=None, **overrides):
        monkeypatch.setattr(
            "app.auctions.load_search_terms",
            lambda *a, **kw: type("T", (), {"active": ("glurak holo",)})(),
        )
        settings = get_settings().model_copy(
            update={"auction_watch_enabled": True, **overrides}
        )
        return AuctionWatcher(
            settings=settings,
            ebay=ebay,
            pokewallet=wallet,
            resolver=_Resolver(resolved),
            notifier=notifier or _Notifier(),
            session_factory=scoped_factory,
            now=lambda: NOW,
        )

    return make


def _resolved():
    from app.models.enums import Language, Printing

    return ResolvedCard(
        "base1-4", "Glurak", "4/102", Language.DE, Printing.HOLO, card_language="de"
    )


def test_scan_stores_and_values_an_auction(watcher_factory, db):
    ebay = _Ebay([_auction()])
    w = watcher_factory(ebay, wallet=_Wallet(Decimal("100")), resolved=_resolved())

    assert w.scan() == 1
    watch = db.query(AuctionWatch).one()
    assert watch.card_name == "Glurak"
    assert watch.reference_value_eur == Decimal("100")
    assert watch.reference_source == "pokewallet"
    # Gesucht wird nur im Fenster — alles andere waere Rauschen.
    assert ebay.searched == [("glurak holo", 45)]


def test_no_alert_while_the_auction_still_runs(watcher_factory, db):
    """Dreissig Minuten vor Schluss sagt der Preis noch nichts."""
    ebay = _Ebay([_auction(minutes=30)], item_price="10.00")
    notifier = _Notifier()
    w = watcher_factory(
        ebay, wallet=_Wallet(Decimal("100")), resolved=_resolved(), notifier=notifier
    )
    w.scan()

    assert w.tick() == 0
    assert notifier.sent == []


def test_alert_shortly_before_the_end_when_far_below_value(watcher_factory, db):
    ebay = _Ebay([_auction(minutes=5)], item_price="60.00")
    notifier = _Notifier()
    w = watcher_factory(
        ebay, wallet=_Wallet(Decimal("100")), resolved=_resolved(), notifier=notifier
    )
    w.scan()

    assert w.tick() == 1
    assert len(notifier.sent) == 1
    content = notifier.sent[0]
    assert "endet in 5 min" in content.title
    assert "40% unter Marktpreis" in content.profit_text
    # Die Grenze der Aussage gehoert in die Meldung.
    assert "kein erzielter Preis" in content.cascade_text
    assert db.query(AuctionWatch).one().alerted_at is not None


def test_a_last_minute_bid_cancels_the_alert(watcher_factory, db):
    """Der Preis von vor vierzig Minuten ist wertlos — es zaehlt das Gebot jetzt."""
    ebay = _Ebay([_auction(minutes=5, price="10.00")], item_price="95.00")
    notifier = _Notifier()
    w = watcher_factory(
        ebay, wallet=_Wallet(Decimal("100")), resolved=_resolved(), notifier=notifier
    )
    w.scan()

    assert w.tick() == 0
    assert notifier.sent == []
    assert db.query(AuctionWatch).one().current_price == Decimal("95.00")


def test_no_double_alert(watcher_factory, db):
    ebay = _Ebay([_auction(minutes=5)], item_price="60.00")
    notifier = _Notifier()
    w = watcher_factory(
        ebay, wallet=_Wallet(Decimal("100")), resolved=_resolved(), notifier=notifier
    )
    w.scan()
    assert w.tick() == 1
    assert w.tick() == 0
    assert len(notifier.sent) == 1


def test_unresolvable_auctions_are_stored_with_a_reason(watcher_factory, db):
    """Auch hier gilt: nicht raten, aber den Grund festhalten."""
    ebay = _Ebay([_auction(title="Pokemon Konvolut 50 Karten")])
    w = watcher_factory(ebay, wallet=_Wallet(Decimal("100")), resolved=None)

    w.scan()
    watch = db.query(AuctionWatch).one()
    assert watch.reference_value_eur is None
    assert "nicht auf genau eine Karte" in watch.skip_reason


def test_foreign_language_auctions_are_identified_but_not_watched(watcher_factory, db):
    from app.models.enums import Language, Printing

    resolved = ResolvedCard(
        "sv1-9", "Oranguru", "9/198", Language.DE, Printing.NORMAL, card_language="it"
    )
    ebay = _Ebay([_auction(title="Oranguru 9/198 Italiano")])
    w = watcher_factory(ebay, wallet=_Wallet(Decimal("100")), resolved=resolved)

    w.scan()
    watch = db.query(AuctionWatch).one()
    assert watch.card_name == "Oranguru"      # erkannt
    assert watch.reference_value_eur is None  # aber nicht bewertet
    assert "'it'" in watch.skip_reason


def test_a_small_discount_is_not_worth_an_alert(watcher_factory, db):
    ebay = _Ebay([_auction(minutes=5)], item_price="85.00")
    notifier = _Notifier()
    w = watcher_factory(
        ebay, wallet=_Wallet(Decimal("100")), resolved=_resolved(), notifier=notifier
    )
    w.scan()
    assert w.tick() == 0   # 15% < 20%
    assert notifier.sent == []
