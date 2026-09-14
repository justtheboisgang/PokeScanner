"""Kauf/Verkauf erfassen (Block 3).

Der Kauf trägt die §25a-UStG-Pflichtfelder (Erwerbsdaten) — ohne sie ist die
Buchhaltung wertlos, deshalb sind sie NOT NULL und werden hier validiert. Der
Verkauf schließt die Position; days_to_sell fällt aus Kauf- und Verkaufsdatum
heraus und speist die Kalibrierung (Prognose vs. Ergebnis).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import PurchaseIn, PurchaseOut, SaleIn, SaleOut
from app.models.candidate import Candidate
from app.models.purchase import Purchase, Sale

router = APIRouter(prefix="/api", tags=["trades"])


@router.post("/purchases", response_model=PurchaseOut, status_code=201)
def create_purchase(payload: PurchaseIn, db: Session = Depends(get_db)) -> Purchase:
    """Kauf erfassen — optional an einen Kandidaten gehängt."""
    if payload.candidate_id is not None:
        candidate = db.get(Candidate, payload.candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        existing = db.scalar(
            select(Purchase).where(Purchase.candidate_id == payload.candidate_id)
        )
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="candidate already has a purchase"
            )

    purchase = Purchase(
        candidate_id=payload.candidate_id,
        price=payload.price,
        date=payload.date,
        channel=payload.channel,
        seller_name=payload.seller_name,
        seller_address=payload.seller_address,
        shipping_cost=payload.shipping_cost,
        currency=payload.currency,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase


@router.post("/purchases/{purchase_id}/sale", response_model=SaleOut, status_code=201)
def create_sale(
    purchase_id: int, payload: SaleIn, db: Session = Depends(get_db)
) -> Sale:
    """Verkauf erfassen und die Position schließen."""
    purchase = db.get(Purchase, purchase_id)
    if purchase is None:
        raise HTTPException(status_code=404, detail="purchase not found")
    existing = db.scalar(select(Sale).where(Sale.purchase_id == purchase_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="purchase already sold")
    if payload.date < purchase.date:
        raise HTTPException(
            status_code=400, detail="sale date is before the purchase date"
        )

    sale = Sale(
        purchase_id=purchase_id,
        price=payload.price,
        date=payload.date,
        channel=payload.channel,
        fees=payload.fees,
        days_to_sell=(payload.date - purchase.date).days,
        currency=payload.currency,
    )
    db.add(sale)
    db.commit()
    db.refresh(sale)
    return sale
