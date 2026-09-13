"""Analytics endpoints: inventory, calibration, costs (§9)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.candidate import Candidate
from app.models.decision import Decision
from app.models.enums import (
    Channel,
    CounterfeitCheck,
    SellerType,
    Verdict,
)
from app.models.listing import Listing
from app.models.purchase import Purchase, Sale
from app.models.usage_event import UsageEvent


def _listing(db, ext, channel=Channel.KLEINANZEIGEN):
    lst = Listing(
        channel=channel,
        external_id=ext,
        title=f"Listing {ext}",
        price=Decimal("60"),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
    )
    db.add(lst)
    db.flush()
    return lst


def test_inventory_exit_ampel(client, db):
    lst = _listing(db, "inv1")
    cand = Candidate(listing_id=lst.id)
    db.add(cand)
    db.flush()
    # Three purchases at different ages -> green / amber / red.
    for ext, days in (("p_green", 10), ("p_amber", 50), ("p_red", 120)):
        db.add(
            Purchase(
                candidate_id=cand.id,
                price=Decimal("60"),
                date=date.today() - timedelta(days=days),
                channel=Channel.KLEINANZEIGEN,
                seller_name="Max",
                seller_address="Str. 1",
            )
        )
    db.commit()

    rows = client.get("/api/inventory").json()
    statuses = {r["days_in_stock"]: r["exit_status"] for r in rows}
    assert statuses[10] == "green"
    assert statuses[50] == "amber"
    assert statuses[120] == "red"


def test_inventory_excludes_sold(client, db):
    lst = _listing(db, "inv2")
    cand = Candidate(listing_id=lst.id)
    db.add(cand)
    db.flush()
    p = Purchase(
        candidate_id=cand.id,
        price=Decimal("60"),
        date=date.today() - timedelta(days=10),
        channel=Channel.KLEINANZEIGEN,
        seller_name="Max",
        seller_address="Str. 1",
    )
    db.add(p)
    db.flush()
    db.add(Sale(purchase_id=p.id, price=Decimal("100"), date=date.today(), channel=Channel.EBAY))
    db.commit()

    assert client.get("/api/inventory").json() == []  # sold -> not open


def test_calibration_aggregates(client, db):
    lst1 = _listing(db, "c1", channel=Channel.KLEINANZEIGEN)
    lst2 = _listing(db, "c2", channel=Channel.EBAY_BROWSE)
    c1 = Candidate(listing_id=lst1.id, alert_sent_at=datetime.now(timezone.utc))
    c2 = Candidate(listing_id=lst2.id)
    db.add_all([c1, c2])
    db.flush()
    db.add(
        Decision(
            candidate_id=c1.id,
            verdict=Verdict.BUY,
            counterfeit_check=CounterfeitCheck.PASSED,
            seconds_since_alert=120,
        )
    )
    db.commit()

    d = client.get("/api/calibration").json()
    assert d["total_candidates"] == 2
    assert d["alerts_per_channel"]["kleinanzeigen"] == 1
    assert d["alerts_per_channel"]["ebay_browse"] == 1
    assert d["unbewertbar_rate"] == 1.0  # neither has a reference value
    assert d["decisions"]["buy"] == 1
    assert d["decided_count"] == 1
    assert d["decision_rate"] == 0.5
    assert d["avg_seconds_to_decision"] == 120.0


def test_costs_usage_and_estimate(client, db):
    db.add_all(
        [
            UsageEvent(source="kleinanzeigen", calls=8),
            UsageEvent(source="kleinanzeigen", calls=8),
            UsageEvent(source="vision", calls=3),
        ]
    )
    lst = _listing(db, "cost1")
    db.add(Candidate(listing_id=lst.id))
    db.commit()

    # No costs configured -> counts only.
    d = client.get("/api/costs").json()
    assert d["costs_configured"] is False
    ka = next(u for u in d["usage"] if u["source"] == "kleinanzeigen")
    assert ka["calls"] == 16
    assert d["cost_per_fund_eur"] is None

    # Configure a vision unit cost -> estimate appears.
    from app.config import get_settings

    get_settings().cost_vision_per_call_eur = Decimal("0.50")
    d2 = client.get("/api/costs").json()
    assert d2["costs_configured"] is True
    vision = next(u for u in d2["usage"] if u["source"] == "vision")
    assert Decimal(vision["est_cost_eur"]) == Decimal("1.50")  # 3 * 0.50
    # funds = 1 -> cost per fund = total (1.50)
    assert Decimal(d2["cost_per_fund_eur"]) == Decimal("1.50")
    get_settings().cost_vision_per_call_eur = Decimal("0")  # reset cached singleton
