"""CostGuard: recording, daily budget enforcement, notify dedupe (Block 0.2)."""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.costs import PROVIDER_ANTHROPIC, PROVIDER_APIFY, PROVIDER_SOLDCOMPS, CostGuard
from app.models.api_cost import ApiCost


def _guard(scoped_factory, **overrides):
    settings = Settings(**overrides)
    return CostGuard(session_factory=scoped_factory, settings=settings)


def test_record_computes_estimated_cost(scoped_factory, db):
    guard = _guard(scoped_factory, COST_APIFY_PER_LISTING_EUR="0.01")
    est = guard.record(PROVIDER_APIFY, "kleinanzeigen", units=50)
    assert est == Decimal("0.50")
    assert db.query(ApiCost).count() == 1
    assert guard.spent_today(PROVIDER_APIFY) == Decimal("0.50")


def test_not_disabled_under_budget(scoped_factory):
    guard = _guard(
        scoped_factory, COST_APIFY_PER_LISTING_EUR="0.01", BUDGET_APIFY_DAILY_EUR="2"
    )
    guard.record(PROVIDER_APIFY, "ka", units=50)  # 0.50 EUR
    assert guard.is_disabled(PROVIDER_APIFY) is False


def test_disabled_when_budget_reached(scoped_factory):
    guard = _guard(
        scoped_factory, COST_APIFY_PER_LISTING_EUR="0.01", BUDGET_APIFY_DAILY_EUR="0.40"
    )
    guard.record(PROVIDER_APIFY, "ka", units=50)  # 0.50 >= 0.40
    assert guard.is_disabled(PROVIDER_APIFY) is True


def test_zero_budget_provider_is_hard_off(scoped_factory):
    guard = _guard(scoped_factory, BUDGET_ANTHROPIC_DAILY_EUR="0")
    assert guard.is_disabled(PROVIDER_ANTHROPIC) is True


def test_notify_dedupe(scoped_factory):
    guard = _guard(scoped_factory)
    assert guard.already_notified_today(PROVIDER_APIFY) is False
    guard.mark_notified(PROVIDER_APIFY)
    assert guard.already_notified_today(PROVIDER_APIFY) is True
    # A notice row must not count toward spend.
    assert guard.spent_today(PROVIDER_APIFY) == Decimal("0")


def test_soldcomps_unit_cost(scoped_factory):
    guard = _guard(scoped_factory, COST_SOLDCOMPS_PER_REQUEST_EUR="0.02")
    assert guard.record(PROVIDER_SOLDCOMPS, "scrape", units=3) == Decimal("0.06")
