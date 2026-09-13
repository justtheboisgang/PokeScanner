"""Block 1 measurement fields: listed_at parsing, time-to-alert, diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingest.kleinanzeigen import normalize_lexis_item, parse_listed_at


def test_parse_listed_at_absolute_day():
    dt, prec = parse_listed_at("02.11.2024")
    assert dt == datetime(2024, 11, 2, tzinfo=timezone.utc)
    assert prec == "day"


def test_parse_listed_at_relative_hours():
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    dt, prec = parse_listed_at("vor 2 Stunden", now=now)
    assert dt == datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)
    assert prec == "hour"


def test_parse_listed_at_heute_gestern():
    now = datetime(2026, 9, 13, 15, 30, tzinfo=timezone.utc)
    dt, prec = parse_listed_at("Heute, 14:05", now=now)
    assert dt == datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    assert prec == "day"
    dt2, _ = parse_listed_at("Gestern", now=now)
    assert dt2 == datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_listed_at_unknown():
    assert parse_listed_at("") == (None, "unknown")
    assert parse_listed_at("blah") == (None, "unknown")


def test_normalize_lexis_sets_listed_at():
    n = normalize_lexis_item(
        {"id": "1", "title": "x", "price": "10.00", "date": "02.11.2024"}
    )
    assert n.listed_at == datetime(2024, 11, 2, tzinfo=timezone.utc)
    assert n.listed_at_precision == "day"
