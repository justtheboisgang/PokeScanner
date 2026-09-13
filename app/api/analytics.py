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
    CostLine,
    CostsSummary,
    InventoryItem,
)
from app.config import get_settings
from app.models.candidate import Candidate
from app.models.decision import Decision
from app.models.purchase import Purchase, Sale
from app.models.usage_event import UsageEvent

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
                purchase_date=p.date,
                days_in_stock=days,
                exit_status=status,
                exit_hint=hint,
            )
        )
    return items


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

    # Forecast error from closed deals.
    sales = db.scalars(
        select(Sale).options(
            joinedload(Sale.purchase).joinedload(Purchase.candidate)
        )
    ).unique().all()
    errors: list[Decimal] = []
    for s in sales:
        p = s.purchase
        cand = p.candidate if p is not None else None
        if cand is None or cand.estimated_profit is None:
            continue
        actual = Decimal(s.price) - Decimal(p.price) - Decimal(p.shipping_cost) - Decimal(s.fees)
        errors.append(actual - Decimal(cand.estimated_profit))

    def _avg(nums) -> float | None:
        return float(sum(nums) / len(nums)) if nums else None

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
    )


# Map a usage source key to its configured per-call cost.
def _unit_cost(source: str) -> Decimal:
    s = get_settings()
    if source in ("kleinanzeigen", "willhaben"):
        return Decimal(str(s.cost_apify_per_run_eur))
    if source == "ebay_browse":
        return Decimal(str(s.cost_ebay_per_call_eur))
    if source == "vision":
        return Decimal(str(s.cost_vision_per_call_eur))
    return Decimal("0")


@router.get("/costs", response_model=CostsSummary)
def costs(db: Session = Depends(get_db)) -> CostsSummary:
    rows = db.execute(
        select(UsageEvent.source, func.sum(UsageEvent.calls)).group_by(UsageEvent.source)
    ).all()

    lines: list[CostLine] = []
    total = Decimal("0")
    configured = False
    for source, calls in rows:
        calls = int(calls or 0)
        unit = _unit_cost(source)
        if unit > 0:
            configured = True
        est = unit * calls
        total += est
        lines.append(
            CostLine(source=source, calls=calls, unit_cost_eur=unit, est_cost_eur=est)
        )
    lines.sort(key=lambda x: x.source)

    funds = db.scalar(select(func.count(Candidate.id))) or 0
    cost_per_fund = (total / funds) if (funds and configured) else None

    return CostsSummary(
        usage=lines,
        total_est_cost_eur=total,
        funds=funds,
        cost_per_fund_eur=cost_per_fund,
        costs_configured=configured,
    )
