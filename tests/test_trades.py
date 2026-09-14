"""Kauf/Verkauf erfassen (Block 3): §25a-Pflichtfelder, Verkauf, Kalibrierung."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.models.candidate import Candidate
from app.models.enums import Channel, ReferenceSource, SellerType
from app.models.listing import Listing
from app.models.reference_value import ReferenceValue
from app.models.card import Card, Variant
from app.models.enums import Condition, Language, Printing


def _listing(db, ext="t1"):
    lst = Listing(
        channel=Channel.KLEINANZEIGEN,
        external_id=ext,
        title="Glurak 4/102",
        price=Decimal("60"),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    return lst


def _candidate(db, ext="t1", estimated_profit=None):
    lst = _listing(db, ext)
    cand = Candidate(listing_id=lst.id, estimated_profit=estimated_profit)
    db.add(cand)
    db.flush()
    return cand


def _purchase_payload(**over):
    body = {
        "price": "60.00",
        "date": "2026-09-01",
        "channel": "kleinanzeigen",
        "seller_name": "Max Mustermann",
        "seller_address": "Musterstr. 1, 12345 Musterstadt",
        "shipping_cost": "5.00",
    }
    body.update(over)
    return body


def test_create_purchase_from_candidate(client, db):
    cand = _candidate(db)
    resp = client.post(
        "/api/purchases", json=_purchase_payload(candidate_id=cand.id)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["candidate_id"] == cand.id
    assert body["seller_name"] == "Max Mustermann"

    # Detail view now knows the candidate was bought.
    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert detail["purchase"]["id"] == body["id"]


def test_purchase_requires_25a_fields(client, db):
    # Blank seller data is rejected — ohne Erwerbsdaten keine Differenzbesteuerung.
    for field in ("seller_name", "seller_address"):
        resp = client.post("/api/purchases", json=_purchase_payload(**{field: "   "}))
        assert resp.status_code == 422, field

    # Missing entirely is rejected too.
    body = _purchase_payload()
    del body["seller_address"]
    assert client.post("/api/purchases", json=body).status_code == 422


def test_purchase_rejects_negative_price(client, db):
    assert client.post(
        "/api/purchases", json=_purchase_payload(price="-1")
    ).status_code == 422


def test_purchase_unknown_candidate_is_404(client, db):
    resp = client.post("/api/purchases", json=_purchase_payload(candidate_id=9999))
    assert resp.status_code == 404


def test_candidate_cannot_be_bought_twice(client, db):
    cand = _candidate(db)
    first = client.post("/api/purchases", json=_purchase_payload(candidate_id=cand.id))
    assert first.status_code == 201
    second = client.post("/api/purchases", json=_purchase_payload(candidate_id=cand.id))
    assert second.status_code == 409


def test_sale_closes_position_and_computes_days(client, db):
    cand = _candidate(db)
    pid = client.post(
        "/api/purchases", json=_purchase_payload(candidate_id=cand.id)
    ).json()["id"]

    # Open position shows in inventory.
    assert any(r["purchase_id"] == pid for r in client.get("/api/inventory").json())

    resp = client.post(
        f"/api/purchases/{pid}/sale",
        json={
            "price": "150.00",
            "date": "2026-09-21",
            "channel": "ebay_browse",
            "fees": "15.00",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["days_to_sell"] == 20  # 2026-09-01 -> 2026-09-21

    # Closed: gone from inventory, present in journal.
    assert not any(r["purchase_id"] == pid for r in client.get("/api/inventory").json())
    journal = client.get("/api/journal").json()
    row = next(r for r in journal if r["purchase_id"] == pid)
    # 150 - 60 - 5 shipping - 15 fees = 70
    assert Decimal(row["actual_profit"]) == Decimal("70.00")


def test_sale_rejects_double_sale_and_bad_date(client, db):
    cand = _candidate(db)
    pid = client.post(
        "/api/purchases", json=_purchase_payload(candidate_id=cand.id)
    ).json()["id"]
    sale = {"price": "100", "date": "2026-09-10", "channel": "kleinanzeigen"}

    assert client.post(f"/api/purchases/{pid}/sale", json=sale).status_code == 201
    assert client.post(f"/api/purchases/{pid}/sale", json=sale).status_code == 409


def test_sale_before_purchase_date_rejected(client, db):
    cand = _candidate(db)
    pid = client.post(
        "/api/purchases", json=_purchase_payload(candidate_id=cand.id)
    ).json()["id"]
    resp = client.post(
        f"/api/purchases/{pid}/sale",
        json={"price": "100", "date": "2026-08-01", "channel": "kleinanzeigen"},
    )
    assert resp.status_code == 400


def test_sale_on_unknown_purchase_is_404(client, db):
    resp = client.post(
        "/api/purchases/9999/sale",
        json={"price": "100", "date": "2026-09-10", "channel": "kleinanzeigen"},
    )
    assert resp.status_code == 404


def test_calibration_reports_forecast_error_per_cascade_level(client, db):
    # A closed deal whose forecast came from cascade level 2.
    card = Card(name="Glurak", tcgdex_id="base1-4")
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
    rv = ReferenceValue(
        variant_id=variant.id,
        value=Decimal("200"),
        currency="EUR",
        source=ReferenceSource.SOLDCOMPS,
        cascade_level=2,
        sample_size=7,
        is_weak=False,
    )
    db.add(rv)
    db.flush()

    cand = _candidate(db, ext="cal1", estimated_profit=Decimal("100"))
    cand.reference_value_id = rv.id
    db.flush()
    db.commit()

    pid = client.post(
        "/api/purchases", json=_purchase_payload(candidate_id=cand.id)
    ).json()["id"]
    client.post(
        f"/api/purchases/{pid}/sale",
        json={
            "price": "150.00",
            "date": "2026-09-21",
            "channel": "ebay_browse",
            "fees": "15.00",
        },
    )

    cal = client.get("/api/calibration").json()
    assert cal["closed_deals"] == 1
    levels = {r["cascade_level"]: r for r in cal["per_cascade_level"]}
    assert 2 in levels
    # actual 70 - forecast 100 = -30
    assert levels[2]["avg_forecast_error_eur"] == -30.0
    assert levels[2]["avg_abs_forecast_error_eur"] == 30.0
    assert levels[2]["closed_deals"] == 1
