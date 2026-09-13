"""Scheduler trigger construction (§11)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from app.config import Settings
from app.scheduler import build_triggers, night_hours


def test_night_hours_complement_of_day_window():
    assert night_hours(8, 23) == [0, 1, 2, 3, 4, 5, 6, 7, 23]
    assert night_hours(0, 24) == []


def test_build_triggers_uses_configured_intervals():
    settings = Settings(
        POLL_DAY_START_HOUR=8,
        POLL_DAY_END_HOUR=23,
        POLL_DAY_INTERVAL_MINUTES=15,
        POLL_NIGHT_INTERVAL_MINUTES=60,
    )
    tz = ZoneInfo("Europe/Berlin")
    day, night = build_triggers(settings, tz)
    day_fields = {f.name: str(f) for f in day.fields}
    night_fields = {f.name: str(f) for f in night.fields}
    # Day: every 15 minutes, hours 8-22.
    assert "*/15" in day_fields["minute"]
    assert "8-22" in day_fields["hour"]
    # Night: top of the hour.
    assert night_fields["minute"] == "0"
