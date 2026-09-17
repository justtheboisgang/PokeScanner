"""Manual evaluation trigger (Block 2.3).

Given an operator-identified list of cards for a listing, resolve/create each
card + variant, run the reference-value cascade (SoldComps) under the cost guard,
persist the reference values and their comps, and compute the listing total value
and estimated profit. Works without a SoldComps key too — then cards are stored
but left unbewertbar until the key is set.
"""

from __future__ import annotations

import inspect
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.pokewallet import MarketPricing, PokeWalletClient
from app.clients.soldcomps import SoldCompsClient
from app.clients.tcgdex import TCGdexClient
from app.config import Settings, get_settings
from app.costs import PROVIDER_SOLDCOMPS, CostGuard
from app.models.candidate import Candidate
from app.models.candidate_card import CandidateCard
from app.models.card import Card, Variant
from app.models.enums import Channel, Condition, Language, Printing
from app.models.market_snapshot import MarketSnapshot
from app.pricing.cascade import CascadeConfig
from app.pricing.resolver import NullResolver, TitleResolver
from app.pricing.service import ReferenceValueCascade, persist_reference_value

logger = logging.getLogger(__name__)

# Channels whose asking price tracks the market closely enough to use it as a
# proxy for what the card is worth. On Kleinanzeigen a low price is exactly the
# edge we are hunting ("weiss nicht was es wert ist"), so the lookup threshold
# must NEVER gate it there — only where the seller prices at market.
_PRICED_AT_MARKET = {Channel.EBAY, Channel.EBAY_BROWSE}

# Laenge der Spalte candidate.valuation_note.
_NOTE_MAX = 200


def _mark_attempt(candidate: Candidate, note: str | None) -> None:
    """Festhalten, DASS bewertet wurde — und woran es ggf. lag.

    Ohne das heisst "unbewertbar" im Feed zweierlei: geprueft und nichts
    gefunden, oder nie angefasst. Der Betreiber muss das unterscheiden koennen,
    sonst haelt er eine nie versuchte Karte fuer wertlos.
    """
    candidate.valuation_attempted_at = datetime.now(timezone.utc)
    candidate.valuation_note = note[:_NOTE_MAX] if note else None


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


def _fetch_market(
    pokewallet: PokeWalletClient | None, card: Card, entry: CardEntry
) -> MarketPricing | None:
    """One ask-side lookup per card: feeds Stufe 4 AND gets stored for analysis."""
    if pokewallet is None or not pokewallet.enabled:
        return None
    try:
        return pokewallet.pricing_for(
            card.name,
            card.number or entry.number,
            prefer_holo=entry.printing in (Printing.HOLO, Printing.REVERSE_HOLO),
        )
    except Exception:
        logger.warning("pokewallet lookup failed for %s", card.name, exc_info=True)
        return None


def _store_market(
    session: Session,
    variant_id: int,
    market: MarketPricing | None,
    reference_value_id: int | None,
) -> None:
    """Keep the market's asking price next to what actually sold.

    Stored even when there is no reference value: a snapshot without a sold
    counterpart still shows what the market claimed at that moment.
    """
    if market is None:
        return
    session.add(
        MarketSnapshot(
            variant_id=variant_id,
            reference_value_id=reference_value_id,
            cm_avg=market.cm_avg,
            cm_low=market.cm_low,
            cm_trend=market.cm_trend,
            cm_avg7=market.cm_avg7,
            cm_avg30=market.cm_avg30,
            tcg_market_usd=market.tcg_market_usd,
            tcg_low_usd=market.tcg_low_usd,
            source="pokewallet",
            source_card_id=market.card_id,
            variant_label=market.variant,
        )
    )


def evaluate_candidate(
    session: Session,
    candidate: Candidate,
    entries: list[CardEntry],
    *,
    settings: Settings | None = None,
    soldcomps: SoldCompsClient | None = None,
    tcgdex: TCGdexClient | None = None,
    pokewallet: PokeWalletClient | None = None,
    card_source: str = "manual",
) -> EvaluationResult:
    settings = settings or get_settings()

    @contextmanager
    def _bind():
        yield session

    guard = CostGuard(session_factory=_bind, settings=settings)
    soldcomps_active = bool(settings.soldcomps_api_key) and not guard.is_disabled(
        PROVIDER_SOLDCOMPS
    )

    # Market data is free and independent of the SoldComps budget, so it is
    # fetched even when the sold side is unavailable — that is exactly when a
    # weak Stufe-4 value is better than nothing.
    if pokewallet is None and settings.pokewallet_api_key:
        pokewallet = PokeWalletClient()

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
            source=card_source,
        )
        session.add(link)
        session.flush()

        market = _fetch_market(pokewallet, card, entry)

        if cascade is not None:
            before = soldcomps.request_count
            try:
                result = cascade.compute(card, variant, market=market)
            except Exception:
                logger.exception("cascade failed for variant %s", variant.id)
                _store_market(session, variant.id, market, None)
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
            _store_market(session, variant.id, market, rv.id if rv else None)
        else:
            _store_market(session, variant.id, market, None)

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

    # Der Versuch ist gelaufen — ob mit Wert oder ohne. Genau diese Notiz
    # unterscheidet spaeter "geprueft, nichts gefunden" von "nie angefasst".
    if have_value:
        _mark_attempt(candidate, None)
    elif not entries:
        _mark_attempt(candidate, "Keine Karten angegeben — nichts zu bewerten.")
    else:
        _mark_attempt(
            candidate,
            note
            or "Geprüft: keine belastbaren Verkaufsdaten gefunden (Kaskade Stufe 5).",
        )

    return EvaluationResult(
        total_value_eur=(total_value if have_value else None),
        estimated_profit_eur=estimated_profit,
        soldcomps_active=soldcomps_active,
        note=note,
    )


def note_unresolvable(candidate: Candidate, trace: list[str]) -> None:
    """Festhalten, warum ein Titel nicht auf genau eine Karte auflösbar war.

    Das kostet nichts (nur TCGdex), deshalb darf auch der Trockenlauf das
    schreiben: er erklärt damit den halben Feed, ohne einen Cent auszugeben.
    """
    reason = trace[-1] if trace else "Titel nicht auf genau eine Karte auflösbar."
    _mark_attempt(candidate, f"Titel nicht eindeutig — {reason}")


def _resolve(
    resolver: TitleResolver, title: str, description: str | None, trace: list[str]
):
    """Den Resolver mit Spur aufrufen, wenn er eine annimmt.

    Das Protokoll verlangt nur (title, description); der echte Resolver bietet
    zusaetzlich ``trace``. Statt darauf zu bauen wird die Signatur gefragt —
    ein TypeError-Fallback wuerde echte Fehler im Resolver verschlucken.
    """
    try:
        takes_trace = "trace" in inspect.signature(resolver.resolve).parameters
    except (TypeError, ValueError):  # z.B. C-implementierte Callables
        takes_trace = False
    if takes_trace:
        return resolver.resolve(title, description, trace=trace)
    return resolver.resolve(title, description)


def auto_value_candidate(
    session: Session,
    candidate: Candidate,
    *,
    resolver: TitleResolver | None = None,
    settings: Settings | None = None,
    soldcomps: SoldCompsClient | None = None,
    tcgdex: TCGdexClient | None = None,
    pokewallet: PokeWalletClient | None = None,
) -> EvaluationResult:
    """Two-gate automatic valuation (Block 2.2).

    Gate 1: the title must unambiguously name exactly one card (the resolver's
    job). Konvolute and vague titles resolve to None and stay unbewertbar — the
    normal case. Gate 2: only spend SoldComps quota when a key is set and the
    daily budget still allows it. Never overrides a manual identification or an
    existing value.
    """
    settings = settings or get_settings()
    resolver = resolver or NullResolver()

    inactive = EvaluationResult(None, None, False, None)

    # Respect manual work / an already-computed value.
    if candidate.reference_value_id is not None:
        return inactive
    # Nur Handarbeit ist tabu. Ein abgebrochener eigener Versuch hinterlaesst
    # ebenfalls Karten (die Verknuepfung entsteht VOR der Bewertung) — den darf
    # und soll die Automatik wiederholen, sonst bleibt die Karte fuer immer
    # unbewertet, nur weil ein Anlauf einmal gescheitert ist.
    identified_by_hand = session.scalar(
        select(func.count())
        .select_from(CandidateCard)
        .where(
            CandidateCard.candidate_id == candidate.id,
            CandidateCard.source == "manual",
        )
    )
    if identified_by_hand:
        return inactive
    listing = candidate.listing
    if listing is None:
        _mark_attempt(candidate, "Kein Listing am Kandidaten — nichts zu bewerten.")
        return inactive

    # Gate 1: unambiguous single card, or nothing. Die Spur des Resolvers ist
    # der Grund: sie sagt, an welchem Tor der Titel gescheitert ist.
    trace: list[str] = []
    resolved = _resolve(resolver, listing.title, listing.description, trace)
    if resolved is None:
        note_unresolvable(candidate, trace)
        return inactive

    # Gate 1c: a lookup costs real money, so skip listings too cheap to yield a
    # worthwhile find — but only where the price actually says something about
    # the card (see _PRICED_AT_MARKET). This is what stops the budget from being
    # spent on Trainer cards worth cents.
    threshold = Decimal(settings.single_card_lookup_threshold_eur)
    if (
        listing.channel in _PRICED_AT_MARKET
        and listing.price is not None
        and Decimal(listing.price) < threshold
        and threshold > 0
    ):
        below = f"Unter der Nachschlagschwelle von {threshold} EUR — nicht bewertet."
        _mark_attempt(candidate, below)
        return EvaluationResult(None, None, False, below)

    # Gate 2: only run (and store) when SoldComps can actually value it today.
    @contextmanager
    def _bind():
        yield session

    guard = CostGuard(session_factory=_bind, settings=settings)
    if not settings.soldcomps_api_key or guard.is_disabled(PROVIDER_SOLDCOMPS):
        blocked = "Titel eindeutig, aber SoldComps nicht verfügbar (kein Key/Budget)."
        _mark_attempt(candidate, blocked)
        return EvaluationResult(None, None, False, blocked)

    entry = CardEntry(
        tcgdex_id=resolved.tcgdex_id,
        name=resolved.name,
        set=None,
        number=resolved.number,
        language=resolved.language,
        # A title never states the condition reliably; stay conservative.
        condition=Condition.UNKNOWN,
        printing=resolved.printing,
        quantity=1,
    )
    return evaluate_candidate(
        session,
        candidate,
        [entry],
        settings=settings,
        soldcomps=soldcomps,
        tcgdex=tcgdex,
        pokewallet=pokewallet,
        card_source="auto",
    )
