"""Web API integration tests (§9)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.candidate import Candidate
from app.models.card import Card, Variant
from app.models.decision import Decision
from app.models.enrichment import Enrichment
from app.models.enums import (
    Channel,
    Condition,
    CounterfeitCheck,
    Language,
    Printing,
    ReferenceSource,
    SellerType,
    Verdict,
)
from app.models.listing import Listing
from app.models.purchase import Purchase, Sale
from app.models.reference_comp import ReferenceComp
from app.models.reference_value import ReferenceValue


def _listing(db, **kw):
    defaults = dict(
        channel=Channel.KLEINANZEIGEN,
        external_id="ext-1",
        title="Alte Pokemon Karten Konvolut",
        description="Vom Dachboden",
        price=Decimal("60.00"),
        currency="EUR",
        location="Berlin",
        seller_type=SellerType.PRIVATE,
        images=["https://img/1.jpg", "https://img/2.jpg"],
        url="https://kleinanzeigen.de/x",
    )
    defaults.update(kw)
    listing = Listing(**defaults)
    db.add(listing)
    db.flush()
    return listing


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_feed_unbewertbar_candidate(client, db):
    listing = _listing(db)
    db.add(
        Candidate(
            listing_id=listing.id,
            estimated_profit=None,
            matched_search_term="alte pokemon karten",
            alert_reason="cheap-gate pass",
            alert_sent_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    rows = client.get("/api/candidates").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["is_unbewertbar"] is True
    assert row["cascade_level"] is None
    assert row["image"] == "https://img/1.jpg"
    assert row["matched_search_term"] == "alte pokemon karten"
    assert row["verdict"] is None


def test_detail_lists_individual_comps(client, db):
    card = Card(name="Glurak", tcgdex_id="base1-4")
    db.add(card)
    db.flush()
    variant = Variant(
        card_id=card.id,
        language=Language.DE,
        condition=Condition.PLAYED,
        printing=Printing.HOLO,
    )
    db.add(variant)
    db.flush()
    rv = ReferenceValue(
        variant_id=variant.id,
        value=Decimal("120.00"),
        currency="EUR",
        source=ReferenceSource.SOLDCOMPS,
        cascade_level=1,
        sample_size=2,
        is_weak=False,
        comps=[
            ReferenceComp(
                price=Decimal("110.00"),
                currency="EUR",
                sold_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                language=Language.DE,
                condition=Condition.PLAYED,
                boa_hydrated=True,
                epid="epid-1",
                source_item_id="item-1",
            ),
            ReferenceComp(
                price=Decimal("130.00"),
                currency="EUR",
                sold_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
                language=Language.DE,
                condition=Condition.PLAYED,
                boa_hydrated=False,
                epid="epid-1",
                source_item_id="item-2",
            ),
        ],
    )
    db.add(rv)
    db.flush()
    listing = _listing(db, external_id="ext-2")
    db.add(
        Candidate(
            listing_id=listing.id,
            reference_value_id=rv.id,
            estimated_profit=Decimal("60.00"),
        )
    )
    db.commit()

    cand_id = client.get("/api/candidates").json()[0]["id"]
    detail = client.get(f"/api/candidates/{cand_id}").json()
    assert detail["reference_value"]["cascade_level"] == 1
    comps = detail["reference_value"]["comps"]
    assert len(comps) == 2
    assert {c["source_item_id"] for c in comps} == {"item-1", "item-2"}
    assert comps[0]["boa_hydrated"] in (True, False)
    assert len(detail["listing"]["images"]) == 2


def test_detail_includes_enrichment(client, db):
    listing = _listing(db, external_id="ext-enrich")
    db.add(listing)
    db.flush()
    cand = Candidate(listing_id=listing.id, matched_search_term="alte pokemon karten")
    db.add(cand)
    db.flush()
    db.add(
        Enrichment(
            candidate_id=cand.id,
            condition_flags=["knick", "kratzer"],
            vision_summary="e-Serie, deutsche Karten",
            vision_model="claude-opus-5",
            vision_used=True,
        )
    )
    db.commit()

    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert detail["enrichment"]["vision_used"] is True
    assert detail["enrichment"]["condition_flags"] == ["knick", "kratzer"]
    assert detail["enrichment"]["vision_summary"] == "e-Serie, deutsche Karten"


def test_detail_404(client):
    assert client.get("/api/candidates/999").status_code == 404


def test_decision_capture_sets_seconds_since_alert(client, db):
    listing = _listing(db, external_id="ext-3")
    db.add(
        Candidate(
            listing_id=listing.id,
            alert_sent_at=datetime.now(timezone.utc) - timedelta(seconds=90),
        )
    )
    db.commit()
    cand_id = client.get("/api/candidates").json()[0]["id"]

    resp = client.put(
        f"/api/candidates/{cand_id}/decision",
        json={
            "verdict": "buy",
            "reason": "drei EX-Karten sichtbar",
            "counterfeit_check": "passed",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "buy"
    assert body["counterfeit_check"] == "passed"
    assert 85 <= body["seconds_since_alert"] <= 120

    # Feed now reflects the verdict.
    assert client.get("/api/candidates").json()[0]["verdict"] == "buy"
    # undecided_only filters it out.
    assert client.get("/api/candidates?undecided_only=true").json() == []


def test_decision_upsert_updates_existing(client, db):
    listing = _listing(db, external_id="ext-4")
    db.add(Candidate(listing_id=listing.id, alert_sent_at=datetime.now(timezone.utc)))
    db.commit()
    cand_id = client.get("/api/candidates").json()[0]["id"]

    client.put(
        f"/api/candidates/{cand_id}/decision",
        json={"verdict": "unclear", "counterfeit_check": "unsure"},
    )
    client.put(
        f"/api/candidates/{cand_id}/decision",
        json={"verdict": "skip", "reason": "Repro-Verdacht", "counterfeit_check": "failed"},
    )
    detail = client.get(f"/api/candidates/{cand_id}").json()
    assert detail["decision"]["verdict"] == "skip"
    assert detail["decision"]["counterfeit_check"] == "failed"
    # Still exactly one decision row.
    assert db.query(Decision).count() == 1


def test_journal_forecast_vs_result(client, db):
    listing = _listing(db, external_id="ext-5")
    candidate = Candidate(
        listing_id=listing.id, estimated_profit=Decimal("50.00")
    )
    db.add(candidate)
    db.flush()
    purchase = Purchase(
        candidate_id=candidate.id,
        price=Decimal("60.00"),
        date=date(2026, 8, 1),
        channel=Channel.KLEINANZEIGEN,
        seller_name="Max M.",
        seller_address="Musterstr. 1, 10115 Berlin",
        shipping_cost=Decimal("5.00"),
    )
    db.add(purchase)
    db.flush()
    db.add(
        Sale(
            purchase_id=purchase.id,
            price=Decimal("140.00"),
            date=date(2026, 8, 20),
            channel=Channel.EBAY,
            fees=Decimal("15.00"),
            days_to_sell=19,
        )
    )
    db.commit()

    rows = client.get("/api/journal").json()
    assert len(rows) == 1
    row = rows[0]
    # actual = 140 - 60 - 5 - 15 = 60
    assert Decimal(row["actual_profit"]) == Decimal("60.00")
    assert Decimal(row["forecast_profit"]) == Decimal("50.00")
    # error = 60 - 50 = 10
    assert Decimal(row["forecast_error"]) == Decimal("10.00")
