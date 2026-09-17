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
from app.models.api_cost import ApiCost
from app.models.listing import Listing
from app.models.purchase import Purchase, Sale


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


def test_costs_per_provider_and_cost_per_fund(client, db):
    db.add_all(
        [
            ApiCost(provider="apify", endpoint="kleinanzeigen", units=100,
                    estimated_cost_eur=Decimal("0.40")),
            ApiCost(provider="soldcomps", endpoint="scrape", units=5,
                    estimated_cost_eur=Decimal("0.20")),
        ]
    )
    # One buy-verdict candidate -> cost per fund = total / 1.
    lst = _listing(db, "cost1")
    cand = Candidate(listing_id=lst.id, alert_sent_at=datetime.now(timezone.utc))
    db.add(cand)
    db.flush()
    db.add(
        Decision(
            candidate_id=cand.id,
            verdict=Verdict.BUY,
            counterfeit_check=CounterfeitCheck.PASSED,
        )
    )
    db.commit()

    d = client.get("/api/costs").json()
    providers = {p["provider"]: p for p in d["providers"]}
    assert Decimal(providers["apify"]["spent_today_eur"]) == Decimal("0.40")
    assert providers["apify"]["disabled"] is False  # under 2 EUR budget
    # anthropic budget is 0 -> always disabled (vision off in V1).
    assert providers["anthropic"]["disabled"] is True
    assert d["buy_count"] == 1
    assert Decimal(d["total_cost_eur"]) == Decimal("0.60")
    assert Decimal(d["cost_per_fund_eur"]) == Decimal("0.60")


def test_diagnostics_per_term_and_time_to_alert(client, db):
    lst1 = _listing(db, "d1")
    lst2 = _listing(db, "d2")
    c1 = Candidate(
        listing_id=lst1.id,
        triggering_search_terms=["alte pokemon karten", "pokemon sammlung"],
        time_to_alert_seconds=100,
    )
    c2 = Candidate(
        listing_id=lst2.id,
        triggering_search_terms=["alte pokemon karten"],
        time_to_alert_seconds=300,
    )
    db.add_all([c1, c2])
    db.flush()
    db.add(
        Decision(
            candidate_id=c1.id,
            verdict=Verdict.BUY,
            counterfeit_check=CounterfeitCheck.PASSED,
        )
    )
    db.commit()

    d = client.get("/api/diagnostics").json()
    assert d["total_candidates"] == 2
    per = {t["term"]: t for t in d["per_term"]}
    assert per["alte pokemon karten"]["candidates"] == 2  # both
    assert per["alte pokemon karten"]["buy"] == 1
    assert per["pokemon sammlung"]["candidates"] == 1
    assert d["time_to_alert_count"] == 2
    assert d["time_to_alert_median_seconds"] == 200.0
    # nothing resolved yet (no reference values)
    assert d["resolver_resolved"] == 0
    # Und auch nichts VERSUCHT: die Quote zaehlt nur echte Versuche, sonst
    # sieht ein unangetasteter Feed nach 0% Erfolg aus statt nach "nie gelaufen".
    assert d["resolver_attempted"] == 0
    assert d["never_attempted"] == 2


def test_costs_no_buys_gives_null_cost_per_fund(client, db):
    db.add(ApiCost(provider="apify", endpoint="x", units=1, estimated_cost_eur=Decimal("0.1")))
    db.commit()
    d = client.get("/api/costs").json()
    assert d["buy_count"] == 0
    assert d["cost_per_fund_eur"] is None


def test_diagnostics_groups_the_reasons_for_unbewertbar(client, db):
    """Die Frage "wieso ist alles unbewertbar?" braucht eine Antwort in Zahlen."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = [
        "Titel nicht eindeutig — Tor 1b: keine Kartennummer wie 4/102 im Titel -> unbewertbar",
        "Titel nicht eindeutig — Tor 1b: keine Kartennummer wie 4/102 im Titel -> unbewertbar",
        "Titel nicht eindeutig — Tor 1a: als Konvolut erkannt (Bundle-Stichwort) -> unbewertbar",
        "Unter der Nachschlagschwelle von 15 EUR — nicht bewertet.",
    ]
    for i, note in enumerate(rows):
        lst = _listing(db, f"reason{i}")
        db.add(
            Candidate(
                listing_id=lst.id,
                valuation_attempted_at=now,
                valuation_note=note,
            )
        )
    # Einer wurde nie angefasst — der darf in der Grund-Tabelle NICHT auftauchen.
    lst = _listing(db, "untouched")
    db.add(Candidate(listing_id=lst.id))
    db.commit()

    d = client.get("/api/diagnostics").json()
    assert d["never_attempted"] == 1
    assert d["resolver_attempted"] == 4
    counts = {r["label"]: r["count"] for r in d["unbewertbar_reasons"]}
    assert counts["keine Kartennummer im Titel (z.B. 4/102)"] == 2
    assert counts["Titel sieht nach Konvolut/Sammlung aus"] == 1
    assert counts["unter der Nachschlagschwelle — bewusst nicht bewertet"] == 1
    # Haeufigster Grund zuerst — sonst muss man die Tabelle lesen statt sehen.
    assert d["unbewertbar_reasons"][0]["count"] == 2
