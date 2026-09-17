"""Analytics endpoints: Inventar, Kalibrierung, Kosten (§9)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.api.schemas import (
    CalibrationSummary,
    CascadeLevelError,
    CostsSummary,
    DiagnosticsReport,
    InventoryItem,
    MarketComparison,
    ProviderCost,
    TermDiagnostic,
)
from app.costs import PROVIDER_ANTHROPIC, PROVIDER_APIFY, PROVIDER_SOLDCOMPS, CostGuard
from app.models.api_cost import ApiCost
from app.models.candidate import Candidate
from app.models.decision import Decision
from app.models.enums import ReferenceSource, Verdict
from app.models.market_snapshot import MarketSnapshot
from app.models.reference_value import ReferenceValue
from app.models.purchase import Purchase, Sale

router = APIRouter(prefix="/api", tags=["analytics"])


def _exit_status(days: int) -> tuple[str, str]:
    if days >= 90:
        return "red", "≥90 Tage: zum Gebot abstoßen"
    if days >= 45:
        return "amber", "≥45 Tage: auf 25. Perzentil repricen"
    return "green", "im Fenster"


@router.get("/inventory", response_model=list[InventoryItem])
def inventory(db: Session = Depends(get_db)) -> list[InventoryItem]:
    """Open positions (a purchase with no sale) with days-in-stock + exit ampel."""
    stmt = (
        select(Purchase)
        .where(~Purchase.sale.has())
        .options(joinedload(Purchase.candidate).joinedload(Candidate.listing))
        .order_by(Purchase.date.asc())
    )
    today = date.today()
    items: list[InventoryItem] = []
    for p in db.scalars(stmt).unique().all():
        days = (today - p.date).days
        status, hint = _exit_status(days)
        title = "(manuell erfasst)"
        if p.candidate is not None and p.candidate.listing is not None:
            title = p.candidate.listing.title
        items.append(
            InventoryItem(
                purchase_id=p.id,
                title=title,
                channel=p.channel,
                seller_name=p.seller_name,
                purchase_price=p.price,
                shipping_cost=p.shipping_cost,
                purchase_date=p.date,
                days_in_stock=days,
                exit_status=status,
                exit_hint=hint,
            )
        )
    return items


def _market_comparison(db: Session) -> MarketComparison | None:
    """Compare sold-based reference values against the market's asking price.

    Only reference values built from REAL sold comps count (Stufe 1-3). A
    Stufe-4 value already comes from market data, so comparing it to market data
    would just measure itself.
    """
    rows = db.execute(
        select(ReferenceValue.value, MarketSnapshot)
        .join(MarketSnapshot, MarketSnapshot.reference_value_id == ReferenceValue.id)
        .where(
            ReferenceValue.source == ReferenceSource.SOLDCOMPS,
            ReferenceValue.cascade_level <= 3,
        )
    ).all()

    ratios: list[float] = []
    sold_values: list[float] = []
    market_values: list[float] = []
    for sold, snap in rows:
        market = (
            snap.cm_avg7 or snap.cm_trend or snap.cm_avg or snap.cm_avg30
        )
        if sold is None or market is None or Decimal(market) <= 0:
            continue
        ratios.append(float(Decimal(sold) / Decimal(market)))
        sold_values.append(float(sold))
        market_values.append(float(market))

    if not ratios:
        return MarketComparison(
            sample_size=0,
            median_ratio=None,
            mean_ratio=None,
            median_sold_eur=None,
            median_market_eur=None,
            verdict="Noch keine Karte mit echtem Verkaufswert UND Marktpreis.",
        )

    from statistics import median

    med = median(ratios)
    if med < 0.75:
        verdict = (
            f"Echte Verkäufe liegen im Mittel bei {med:.0%} des Marktpreises — "
            "Cardmarket-Preise sind hier deutlich zu hoch."
        )
    elif med < 0.95:
        verdict = (
            f"Echte Verkäufe liegen bei {med:.0%} des Marktpreises — "
            "der Markt ist leicht überzeichnet."
        )
    elif med <= 1.1:
        verdict = f"Verkäufe und Marktpreis decken sich weitgehend ({med:.0%})."
    else:
        verdict = (
            f"Echte Verkäufe liegen bei {med:.0%} des Marktpreises — "
            "der Markt hinkt nach oben hinterher."
        )

    return MarketComparison(
        sample_size=len(ratios),
        median_ratio=med,
        mean_ratio=sum(ratios) / len(ratios),
        median_sold_eur=median(sold_values),
        median_market_eur=median(market_values),
        verdict=verdict,
    )


@router.get("/calibration", response_model=CalibrationSummary)
def calibration(db: Session = Depends(get_db)) -> CalibrationSummary:
    candidates = db.scalars(
        select(Candidate).options(
            joinedload(Candidate.listing),
            joinedload(Candidate.decision),
        )
    ).unique().all()
    total = len(candidates)

    alerts_per_channel: dict[str, int] = {}
    unbewertbar = 0
    decisions: dict[str, int] = {}
    seconds: list[int] = []
    for c in candidates:
        if c.listing is not None:
            ch = c.listing.channel.value
            alerts_per_channel[ch] = alerts_per_channel.get(ch, 0) + 1
        if c.reference_value_id is None:
            unbewertbar += 1
        if c.decision is not None:
            v = c.decision.verdict.value
            decisions[v] = decisions.get(v, 0) + 1
            if c.decision.seconds_since_alert is not None:
                seconds.append(c.decision.seconds_since_alert)

    decided = sum(decisions.values())

    # Forecast error from closed deals, overall and per cascade level.
    sales = db.scalars(
        select(Sale).options(
            joinedload(Sale.purchase)
            .joinedload(Purchase.candidate)
            .joinedload(Candidate.reference_value)
        )
    ).unique().all()
    errors: list[Decimal] = []
    per_level: dict[int, list[Decimal]] = {}
    for s in sales:
        p = s.purchase
        cand = p.candidate if p is not None else None
        if cand is None or cand.estimated_profit is None:
            continue
        actual = Decimal(s.price) - Decimal(p.price) - Decimal(p.shipping_cost) - Decimal(s.fees)
        error = actual - Decimal(cand.estimated_profit)
        errors.append(error)
        # Which cascade level produced that forecast? That is the thing to judge.
        rv = cand.reference_value
        if rv is not None:
            per_level.setdefault(rv.cascade_level, []).append(error)

    def _avg(nums) -> float | None:
        return float(sum(nums) / len(nums)) if nums else None

    level_rows = [
        CascadeLevelError(
            cascade_level=level,
            closed_deals=len(errs),
            avg_forecast_error_eur=_avg(errs),
            avg_abs_forecast_error_eur=_avg([abs(e) for e in errs]),
        )
        for level, errs in sorted(per_level.items())
    ]

    return CalibrationSummary(
        total_candidates=total,
        alerts_per_channel=alerts_per_channel,
        unbewertbar_rate=(unbewertbar / total if total else None),
        decisions=decisions,
        decided_count=decided,
        decision_rate=(decided / total if total else None),
        avg_seconds_to_decision=_avg(seconds),
        closed_deals=len(sales),
        avg_forecast_error_eur=_avg(errors),
        avg_abs_forecast_error_eur=_avg([abs(e) for e in errors]),
        per_cascade_level=level_rows,
        market_comparison=_market_comparison(db),
    )


def _percentile(values: list[int], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


@router.get("/diagnostics", response_model=DiagnosticsReport)
def diagnostics(db: Session = Depends(get_db)) -> DiagnosticsReport:
    """Measurement report (§1.5): finds per term, verdict split, time-to-alert."""
    candidates = db.scalars(
        select(Candidate).options(joinedload(Candidate.decision))
    ).unique().all()
    total = len(candidates)

    per_term: dict[str, dict[str, int]] = {}
    times: list[int] = []
    resolved = 0
    for c in candidates:
        if c.reference_value_id is not None:
            resolved += 1
        if c.time_to_alert_seconds is not None:
            times.append(c.time_to_alert_seconds)
        terms = list(c.triggering_search_terms or [])
        if not terms:
            terms = [c.matched_search_term or "—"]
        verdict = c.decision.verdict.value if c.decision else "undecided"
        for term in terms:
            row = per_term.setdefault(
                term, {"candidates": 0, "buy": 0, "skip": 0, "unclear": 0, "undecided": 0}
            )
            row["candidates"] += 1
            row[verdict] = row.get(verdict, 0) + 1

    term_rows = [
        TermDiagnostic(
            term=term,
            candidates=r["candidates"],
            share=(r["candidates"] / total if total else 0.0),
            buy=r["buy"],
            skip=r["skip"],
            unclear=r["unclear"],
            undecided=r["undecided"],
        )
        for term, r in per_term.items()
    ]
    term_rows.sort(key=lambda x: x.candidates, reverse=True)

    from statistics import median

    return DiagnosticsReport(
        total_candidates=total,
        per_term=term_rows,
        time_to_alert_count=len(times),
        time_to_alert_median_seconds=(float(median(times)) if times else None),
        time_to_alert_p90_seconds=_percentile(times, 0.9),
        resolver_attempted=total,
        resolver_resolved=resolved,
    )


@router.get("/costs", response_model=CostsSummary)
def costs(db: Session = Depends(get_db)) -> CostsSummary:
    """Per-provider spend today + cost per buy-verdict fund (Block 0.3)."""
    # A guard bound to this request's session for today's spend + budgets.
    guard = CostGuard(session_factory=lambda: _NullCtx(db))

    providers: list[ProviderCost] = []
    for provider in (PROVIDER_APIFY, PROVIDER_SOLDCOMPS, PROVIDER_ANTHROPIC):
        providers.append(
            ProviderCost(
                provider=provider,
                spent_today_eur=guard.spent_today(provider),
                budget_eur=guard.budget(provider),
                disabled=guard.is_disabled(provider),
            )
        )

    total = Decimal(
        str(db.scalar(select(func.coalesce(func.sum(ApiCost.estimated_cost_eur), 0))) or 0)
    )
    buy_count = (
        db.scalar(
            select(func.count(Decision.id)).where(Decision.verdict == Verdict.BUY)
        )
        or 0
    )
    cost_per_fund = (total / buy_count) if buy_count else None

    return CostsSummary(
        providers=providers,
        total_cost_eur=total,
        buy_count=buy_count,
        cost_per_fund_eur=cost_per_fund,
    )


class _NullCtx:
    """Wrap an existing Session as a context manager the guard can use read-only."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self) -> Session:
        return self._session

    def __exit__(self, *exc: object) -> bool:
        return False
