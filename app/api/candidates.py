"""Candidate endpoints: live feed, detail, decision capture (§9)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from decimal import Decimal

from app.api.deps import get_db
from app.api.schemas import (
    CandidateCardOut,
    CandidateDetail,
    CandidateFeedItem,
    DecisionIn,
    DecisionOut,
    EvaluateRequest,
    EvaluationResponse,
)
from app.models.candidate import Candidate
from app.models.candidate_card import CandidateCard
from app.models.card import Variant
from app.models.decision import Decision
from app.models.purchase import Purchase
from app.models.reference_value import ReferenceValue
from app.pricing.evaluate import CardEntry, evaluate_candidate

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


def _feed_item(candidate: Candidate) -> CandidateFeedItem:
    listing = candidate.listing
    rv = candidate.reference_value
    return CandidateFeedItem(
        id=candidate.id,
        title=listing.title,
        price=listing.price,
        currency=listing.currency,
        image=(listing.images[0] if listing.images else None),
        location=listing.location,
        channel=listing.channel,
        matched_search_term=candidate.matched_search_term,
        estimated_profit=candidate.estimated_profit,
        cascade_level=(rv.cascade_level if rv else None),
        sample_size=(rv.sample_size if rv else None),
        is_weak=(rv.is_weak if rv else False),
        is_unbewertbar=rv is None,
        valuation_attempted_at=candidate.valuation_attempted_at,
        valuation_note=candidate.valuation_note,
        alert_sent_at=candidate.alert_sent_at,
        created_at=candidate.created_at,
        verdict=(candidate.decision.verdict if candidate.decision else None),
    )


@router.get("", response_model=list[CandidateFeedItem])
def list_candidates(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    undecided_only: bool = Query(False),
) -> list[CandidateFeedItem]:
    """Live feed, newest first."""
    stmt = (
        select(Candidate)
        .options(
            joinedload(Candidate.listing),
            joinedload(Candidate.reference_value),
            joinedload(Candidate.decision),
        )
        .order_by(Candidate.created_at.desc(), Candidate.id.desc())
    )
    if undecided_only:
        stmt = stmt.where(~Candidate.decision.has())
    stmt = stmt.limit(limit).offset(offset)
    return [_feed_item(c) for c in db.scalars(stmt).unique().all()]


def _load_detail(db: Session, candidate_id: int) -> Candidate:
    stmt = (
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(
            joinedload(Candidate.listing),
            joinedload(Candidate.reference_value).selectinload(ReferenceValue.comps),
            joinedload(Candidate.decision),
            joinedload(Candidate.enrichment),
            selectinload(Candidate.cards)
            .joinedload(CandidateCard.variant)
            .joinedload(Variant.card),
            selectinload(Candidate.cards)
            .joinedload(CandidateCard.reference_value)
            .selectinload(ReferenceValue.comps),
        )
    )
    candidate = db.scalars(stmt).unique().one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate


def _card_out(cc: CandidateCard) -> CandidateCardOut:
    card = cc.variant.card
    return CandidateCardOut(
        id=cc.id,
        name=card.name,
        set=card.set,
        number=card.number,
        language=cc.variant.language,
        condition=cc.variant.condition,
        printing=cc.variant.printing,
        quantity=cc.quantity,
        reference_value=cc.reference_value,
    )


def _detail(candidate: Candidate, purchase: Purchase | None = None) -> CandidateDetail:
    cards = [_card_out(cc) for cc in candidate.cards]
    total = Decimal("0")
    have = False
    for cc in candidate.cards:
        if cc.reference_value is not None:
            total += Decimal(cc.reference_value.value) * cc.quantity
            have = True
    return CandidateDetail(
        id=candidate.id,
        listing=candidate.listing,
        estimated_profit=candidate.estimated_profit,
        alert_reason=candidate.alert_reason,
        matched_search_term=candidate.matched_search_term,
        alert_sent_at=candidate.alert_sent_at,
        reference_value=candidate.reference_value,
        valuation_attempted_at=candidate.valuation_attempted_at,
        valuation_note=candidate.valuation_note,
        decision=candidate.decision,
        enrichment=candidate.enrichment,
        cards=cards,
        cards_total_value_eur=(total if have else None),
        purchase=purchase,
    )


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(
    candidate_id: int, db: Session = Depends(get_db)
) -> CandidateDetail:
    candidate = _load_detail(db, candidate_id)
    purchase = db.scalar(select(Purchase).where(Purchase.candidate_id == candidate_id))
    return _detail(candidate, purchase)


@router.post("/{candidate_id}/evaluate", response_model=EvaluationResponse)
def evaluate(
    candidate_id: int, payload: EvaluateRequest, db: Session = Depends(get_db)
) -> EvaluationResponse:
    """Manual evaluation (Block 2.3): run the cascade for operator-identified cards."""
    candidate = _load_detail(db, candidate_id)
    entries = [
        CardEntry(
            tcgdex_id=c.tcgdex_id,
            name=c.name,
            set=c.set,
            number=c.number,
            language=c.language,
            condition=c.condition,
            printing=c.printing,
            quantity=c.quantity,
        )
        for c in payload.cards
    ]
    result = evaluate_candidate(db, candidate, entries)
    db.commit()
    return EvaluationResponse(
        total_value_eur=result.total_value_eur,
        estimated_profit_eur=result.estimated_profit_eur,
        soldcomps_active=result.soldcomps_active,
        note=result.note,
    )


@router.put("/{candidate_id}/decision", response_model=DecisionOut)
def upsert_decision(
    candidate_id: int, payload: DecisionIn, db: Session = Depends(get_db)
) -> DecisionOut:
    """Record (or update) the Buy/Skip/Unclear verdict + counterfeit check (§7/§9)."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")

    seconds_since_alert: int | None = None
    if candidate.alert_sent_at is not None:
        sent = candidate.alert_sent_at
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=timezone.utc)
        seconds_since_alert = int(
            (datetime.now(timezone.utc) - sent).total_seconds()
        )

    decision = db.scalar(
        select(Decision).where(Decision.candidate_id == candidate_id)
    )
    if decision is None:
        decision = Decision(candidate_id=candidate_id)
        db.add(decision)
    decision.verdict = payload.verdict
    decision.reason = payload.reason
    decision.counterfeit_check = payload.counterfeit_check
    decision.seconds_since_alert = seconds_since_alert

    db.commit()
    db.refresh(decision)
    return decision
