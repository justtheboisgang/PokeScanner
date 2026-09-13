"""CostGuard: record every external call and enforce a daily per-provider budget.

Not a "log a warning and continue" flag — a real gate (Block 0.2): once a
provider's estimated spend for the day reaches its budget, `is_disabled` returns
True and callers must skip that provider for the rest of the day. A budget of 0
means the provider is hard-off.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import session_scope
from app.models.api_cost import ApiCost

PROVIDER_APIFY = "apify"
PROVIDER_SOLDCOMPS = "soldcomps"
PROVIDER_ANTHROPIC = "anthropic"

_NOTICE_ENDPOINT = "__budget_exceeded_notice__"


class CostGuard:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()

    # -- config lookups ----------------------------------------------------

    def unit_cost(self, provider: str) -> Decimal:
        if provider == PROVIDER_APIFY:
            return Decimal(str(self.settings.cost_apify_per_listing_eur))
        if provider == PROVIDER_SOLDCOMPS:
            return Decimal(str(self.settings.cost_soldcomps_per_request_eur))
        return Decimal("0")  # anthropic: vision off in V1

    def budget(self, provider: str) -> Decimal:
        if provider == PROVIDER_APIFY:
            return Decimal(str(self.settings.budget_apify_daily_eur))
        if provider == PROVIDER_SOLDCOMPS:
            return Decimal(str(self.settings.budget_soldcomps_daily_eur))
        if provider == PROVIDER_ANTHROPIC:
            return Decimal(str(self.settings.budget_anthropic_daily_eur))
        return Decimal("0")

    def _day_start(self) -> datetime:
        """Local (configured tz) midnight, as a tz-aware UTC instant."""
        tz = ZoneInfo(self.settings.scheduler_timezone)
        local_midnight = datetime.now(tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return local_midnight.astimezone(timezone.utc)

    # -- reads -------------------------------------------------------------

    def spent_today(self, provider: str) -> Decimal:
        with self.session_factory() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(ApiCost.estimated_cost_eur), 0)).where(
                    ApiCost.provider == provider,
                    ApiCost.created_at >= self._day_start(),
                )
            )
        return Decimal(str(total or 0))

    def is_disabled(self, provider: str) -> bool:
        b = self.budget(provider)
        if b <= 0:
            return True  # budget 0 => provider hard-off
        return self.spent_today(provider) >= b

    def already_notified_today(self, provider: str) -> bool:
        with self.session_factory() as session:
            row = session.scalar(
                select(ApiCost.id).where(
                    ApiCost.provider == provider,
                    ApiCost.endpoint == _NOTICE_ENDPOINT,
                    ApiCost.created_at >= self._day_start(),
                ).limit(1)
            )
        return row is not None

    # -- writes ------------------------------------------------------------

    def record(
        self,
        provider: str,
        endpoint: str,
        units: int,
        *,
        candidate_id: int | None = None,
    ) -> Decimal:
        """Record a call's estimated cost. Returns the estimated euro amount."""
        est = self.unit_cost(provider) * Decimal(units)
        with self.session_factory() as session:
            session.add(
                ApiCost(
                    provider=provider,
                    endpoint=endpoint,
                    units=units,
                    estimated_cost_eur=est,
                    candidate_id=candidate_id,
                )
            )
        return est

    def mark_notified(self, provider: str) -> None:
        with self.session_factory() as session:
            session.add(
                ApiCost(
                    provider=provider,
                    endpoint=_NOTICE_ENDPOINT,
                    units=0,
                    estimated_cost_eur=Decimal("0"),
                )
            )
