"""Auktions-Wache auf der Website (§9).

Zeigt, was die Wache gerade beobachtet: was wann endet, wie weit das aktuelle
Gebot unter dem Marktpreis liegt — und wo sie sich heraushaelt und warum.
Die Meldung auf Discord kommt fuenf Minuten vor Schluss; diese Seite ist der
Blick davor, damit man nicht ueberrascht wird.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import AuctionItem
from app.config import get_settings
from app.models.auction_watch import AuctionWatch

router = APIRouter(prefix="/api/auctions", tags=["auctions"])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _item(watch: AuctionWatch, now: datetime, threshold: int) -> AuctionItem:
    ends_at = _aware(watch.ends_at)
    seconds_left = int((ends_at - now).total_seconds())
    discount = None
    if (
        watch.reference_value_eur is not None
        and watch.reference_value_eur > 0
        and watch.current_price is not None
    ):
        discount = float(
            (watch.reference_value_eur - watch.current_price)
            / watch.reference_value_eur
            * 100
        )
    return AuctionItem(
        id=watch.id,
        title=watch.title,
        url=watch.url,
        image=watch.image,
        currency=watch.currency,
        current_price=watch.current_price,
        ends_at=ends_at,
        seconds_left=seconds_left,
        reference_value_eur=watch.reference_value_eur,
        reference_source=watch.reference_source,
        discount_pct=discount,
        # Ob es fuer einen Alarm reicht, entscheidet dieselbe Schwelle wie im
        # Worker — sonst zeigt die Seite etwas anderes an, als gemeldet wird.
        would_alert=(discount is not None and discount >= threshold),
        card_name=watch.card_name,
        card_number=watch.card_number,
        skip_reason=watch.skip_reason,
        matched_search_term=watch.matched_search_term,
        alerted_at=watch.alerted_at,
        checked_at=watch.checked_at,
    )


@router.get("", response_model=list[AuctionItem])
def list_auctions(
    db: Session = Depends(get_db),
    include_past: bool = Query(False, description="Auch bereits beendete zeigen"),
    limit: int = Query(100, ge=1, le=300),
) -> list[AuctionItem]:
    """Beobachtete Auktionen, die naechste zuerst."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    watches = db.scalars(
        select(AuctionWatch).order_by(AuctionWatch.ends_at.asc()).limit(limit * 3)
    ).all()
    items = [
        _item(w, now, settings.auction_min_discount_pct)
        for w in watches
        if include_past or _aware(w.ends_at) > now
    ]
    # Die naechste Auktion zuerst — beendete ans Ende, sonst stehen sie oben.
    items.sort(key=lambda i: (i.seconds_left < 0, i.seconds_left))
    return items[:limit]
