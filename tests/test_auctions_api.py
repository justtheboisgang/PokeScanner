"""Auktions-Wache auf der Website."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.auction_watch import AuctionWatch


def _watch(db, ends_in_minutes, price="60", value="100", **kw):
    watch = AuctionWatch(
        external_id=kw.pop("ext", f"v1|{ends_in_minutes}|0"),
        title=kw.pop("title", "Glurak 4/102 Holo Deutsch"),
        url="https://ebay.de/itm/1",
        image=None,
        currency="EUR",
        ends_at=datetime.now(timezone.utc) + timedelta(minutes=ends_in_minutes),
        current_price=Decimal(price) if price is not None else None,
        reference_value_eur=Decimal(value) if value is not None else None,
        reference_source="pokewallet",
        card_name="Glurak",
        card_number="4/102",
        **kw,
    )
    db.add(watch)
    db.commit()
    return watch


def test_running_auctions_are_listed_soonest_first(client, db):
    _watch(db, 40, ext="a")
    _watch(db, 5, ext="b")
    _watch(db, 20, ext="c")

    rows = client.get("/api/auctions").json()
    assert [r["seconds_left"] > 0 for r in rows] == [True, True, True]
    assert rows[0]["seconds_left"] < rows[1]["seconds_left"] < rows[2]["seconds_left"]


def test_the_discount_is_computed_and_flagged(client, db):
    _watch(db, 10, price="60", value="100")
    row = client.get("/api/auctions").json()[0]
    assert round(row["discount_pct"]) == 40
    assert row["would_alert"] is True
    assert row["card_name"] == "Glurak"


def test_a_small_discount_is_shown_but_not_flagged(client, db):
    _watch(db, 10, price="90", value="100")
    row = client.get("/api/auctions").json()[0]
    assert round(row["discount_pct"]) == 10
    assert row["would_alert"] is False


def test_unwatched_auctions_say_why(client, db):
    _watch(db, 10, value=None, skip_reason="Titel nicht auflösbar")
    row = client.get("/api/auctions").json()[0]
    assert row["reference_value_eur"] is None
    assert row["discount_pct"] is None
    assert row["would_alert"] is False
    assert row["skip_reason"] == "Titel nicht auflösbar"


def test_finished_auctions_are_hidden_unless_asked_for(client, db):
    _watch(db, -30, ext="past")
    assert client.get("/api/auctions").json() == []
    rows = client.get("/api/auctions?include_past=true").json()
    assert len(rows) == 1
    assert rows[0]["seconds_left"] < 0
