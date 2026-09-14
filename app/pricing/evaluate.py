"""Manual evaluation trigger (Block 2.3).

Given an operator-identified list of cards for a listing, resolve/create each
card + variant, run the reference-value cascade (SoldComps) under the cost guard,
persist the reference values and their comps, and compute the listing total value
and estimated profit. Works without a SoldComps key too — then cards are stored
but left unbewertbar until the key is set.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.soldcomps import SoldCompsClient
from app.clients.tcgdex import TCGdexClient
from app.config import Settings, get_settings
from app.costs import PROVIDER_SOLDCOMPS, CostGuard
from app.models.candidate import Candidate
from app.models.candidate_card import CandidateCard
from app.models.card import Card, Variant
from app.models.enums import Condition, Language, Printing
from app.pricing.cascade import CascadeConfig
from app.pricing.service import ReferenceValueCascade, persist_reference_value

logger = logging.getLogger(__name__)


@dataclass
class CardEntry:
    tcgdex_id: str | None
    name: str
    set: str | None
    number: str | None
    language: Language
    condition: Condition
    printing: Printing
    quantity: int = 1


@dataclass
class EvaluationResult:
    total_value_eur: Decimal | None
    estimated_profit_eur: Decimal | None
    soldcomps_active: bool
    note: str | None = None


def _get_or_create_card(session: Session, entry: CardEntry) -> Card:
    if entry.tcgdex_id:
        card = session.scalar(select(Card).where(Card.tcgdex_id == entry.tcgdex_id))
        if card is not None:
            return card
    card = Card(
        name=entry.name,
        set=entry.set,
        number=entry.number,
        tcgdex_id=entry.tcgdex_id,
    )
    session.add(card)
    session.flush()
    return card


def _get_or_create_variant(session: Session, card: Card, entry: CardEntry) -> Variant:
    variant = session.scalar(
        select(Variant).where(
            Variant.card_id == card.id,
            Variant.language == entry.language,
            Variant.condition == entry.condition,
            Variant.printing == entry.printing,
        )
    )
    if variant is not None:
        return variant
    variant = Variant(
        card_id=card.id,
        language=entry.language,
        condition=entry.condition,
        printing=entry.printing,
    )
    session.add(variant)
    session.flush()
    return variant


def evaluate_candidate(
    session: Session,
    candidate: Candidate,
    entries: list[CardEntry],
    *,
    settings: Settings | None = None,
    soldcomps: SoldCompsClient | None = None,
    tcgdex: TCGdexClient | None = None,
) -> EvaluationResult:
    settings = settings or get_settings()

    @contextmanager
    def _bind():
        yield session

    guard = CostGuard(session_factory=_bind, settings=settings)
    soldcomps_active = bool(settings.soldcomps_api_key) and not guard.is_disabled(
        PROVIDER_SOLDCOMPS
    )

    cascade = None
    if soldcomps_active:
        soldcomps = soldcomps or SoldCompsClient()
        tcgdex = tcgdex or TCGdexClient()
        cascade = ReferenceValueCascade(
            soldcomps, tcgdex, CascadeConfig.from_settings()
        )

    # Replace any prior identifications for this candidate. Query rather than
    # relying on candidate.cards, so re-evaluation is correct even if the caller
    # holds a candidate whose relationship collection is stale.
    for old in session.scalars(
        select(CandidateCard).where(CandidateCard.candidate_id == candidate.id)
    ).all():
        session.delete(old)
    session.flush()
    if "cards" in candidate.__dict__:
        session.expire(candidate, ["cards"])

    total_value = Decimal("0")
    have_value = False
    first_rv_id: int | None = None

    for entry in entries:
        card = _get_or_create_card(session, entry)
        variant = _get_or_create_variant(session, card, entry)
        link = CandidateCard(
            candidate_id=candidate.id,
            variant_id=variant.id,
            quantity=max(1, entry.quantity),
        )
        session.add(link)
        session.flush()

        if cascade is not None:
            before = soldcomps.request_count
            try:
                result = cascade.compute(card, variant)
            except Exception:
                logger.exception("cascade failed for variant %s", variant.id)
                continue
            finally:
                delta = soldcomps.request_count - before
                if delta > 0:
                    guard.record(
                        PROVIDER_SOLDCOMPS, "scrape", units=delta,
                        candidate_id=candidate.id,
                    )
            rv = persist_reference_value(session, variant.id, result)
            if rv is not None:
                session.flush()
                link.reference_value_id = rv.id
                first_rv_id = first_rv_id or rv.id
                total_value += Decimal(result.value) * link.quantity
                have_value = True

    # Update the candidate's estimate (never retract the alert; just annotate).
    estimated_profit: Decimal | None = None
    if have_value:
        candidate.reference_value_id = first_rv_id
        if candidate.listing is not None and candidate.listing.price is not None:
            estimated_profit = total_value - Decimal(candidate.listing.price)
        candidate.estimated_profit = estimated_profit

    note = None
    if not settings.soldcomps_api_key:
        note = "SoldComps ist nicht konfiguriert (SOLDCOMPS_API_KEY) — Karten wurden erfasst, aber nicht bewertet."
    elif not soldcomps_active:
        note = "SoldComps-Tagesbudget erreicht — heute keine Bewertung möglich."

    return EvaluationResult(
        total_value_eur=(total_value if have_value else None),
        estimated_profit_eur=estimated_profit,
        soldcomps_active=soldcomps_active,
        note=note,
    )
