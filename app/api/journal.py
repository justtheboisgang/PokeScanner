"""Journal endpoint: completed deals, forecast vs. result (§9)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.api.schemas import JournalItem
from app.models.purchase import Purchase, Sale

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("", response_model=list[JournalItem])
def list_journal(db: Session = Depends(get_db)) -> list[JournalItem]:
    """Closed positions (a sale exists), newest sale first."""
    stmt = (
        select(Sale)
        .join(Sale.purchase)
        .options(joinedload(Sale.purchase).joinedload(Purchase.candidate))
        .order_by(Sale.date.desc(), Sale.id.desc())
    )
    items: list[JournalItem] = []
    for sale in db.scalars(stmt).unique().all():
        purchase = sale.purchase
        actual_profit = (
            Decimal(sale.price)
            - Decimal(purchase.price)
            - Decimal(purchase.shipping_cost)
            - Decimal(sale.fees)
        )
        forecast_profit = (
            purchase.candidate.estimated_profit
            if purchase.candidate is not None
            else None
        )
        forecast_error = (
            actual_profit - forecast_profit if forecast_profit is not None else None
        )
        items.append(
            JournalItem(
                purchase_id=purchase.id,
                purchase_price=purchase.price,
                purchase_date=purchase.date,
                shipping_cost=purchase.shipping_cost,
                seller_name=purchase.seller_name,
                channel=sale.channel,
                sale_price=sale.price,
                sale_date=sale.date,
                fees=sale.fees,
                days_to_sell=sale.days_to_sell,
                actual_profit=actual_profit,
                forecast_profit=forecast_profit,
                forecast_error=forecast_error,
            )
        )
    return items
