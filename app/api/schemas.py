"""Pydantic schemas for the web API (§9)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    Channel,
    Condition,
    CounterfeitCheck,
    Language,
    Printing,
    ReferenceSource,
    SellerType,
    Verdict,
)


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: Channel
    external_id: str
    title: str
    description: str | None
    price: Decimal | None
    currency: str
    location: str | None
    seller_type: SellerType
    images: list[str]
    url: str | None
    first_seen_at: datetime
    last_seen_at: datetime


class ReferenceCompOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    price: Decimal
    currency: str
    sold_at: datetime | None
    language: Language
    condition: Condition
    boa_hydrated: bool
    epid: str | None
    source_item_id: str | None


class ReferenceValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    value: Decimal
    currency: str
    source: ReferenceSource
    cascade_level: int
    sample_size: int
    is_weak: bool
    computed_at: datetime
    comps: list[ReferenceCompOut] = []


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    verdict: Verdict
    reason: str | None
    counterfeit_check: CounterfeitCheck
    decided_at: datetime
    seconds_since_alert: int | None


class DecisionIn(BaseModel):
    verdict: Verdict
    reason: str | None = None
    # Mandatory counterfeit-check step (§7). Im Zweifel: nicht kaufen.
    counterfeit_check: CounterfeitCheck


class CandidateFeedItem(BaseModel):
    """Live-feed row: image, price, estimated profit, cascade level (§9)."""

    id: int
    title: str
    price: Decimal | None
    currency: str
    image: str | None
    location: str | None
    channel: Channel
    matched_search_term: str | None
    estimated_profit: Decimal | None
    cascade_level: int | None
    sample_size: int | None
    is_weak: bool
    is_unbewertbar: bool
    # Getrennt ausgewiesen: ohne Versuchszeitpunkt heisst "unbewertbar" nur
    # "noch nicht bewertet" — ein Unterschied, den der Betreiber braucht.
    valuation_attempted_at: datetime | None = None
    valuation_note: str | None = None
    alert_sent_at: datetime | None
    created_at: datetime
    verdict: Verdict | None


class EnrichmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    condition_flags: list[str] = []
    vision_summary: str | None
    vision_model: str | None
    vision_used: bool
    enriched_at: datetime


class CandidateCardOut(BaseModel):
    id: int
    name: str
    set: str | None
    number: str | None
    language: Language
    condition: Condition
    printing: Printing
    quantity: int
    reference_value: ReferenceValueOut | None


class CandidateDetail(BaseModel):
    id: int
    listing: ListingOut
    estimated_profit: Decimal | None
    alert_reason: str | None
    matched_search_term: str | None
    alert_sent_at: datetime | None
    reference_value: ReferenceValueOut | None
    valuation_attempted_at: datetime | None = None
    valuation_note: str | None = None
    decision: DecisionOut | None
    enrichment: EnrichmentOut | None
    cards: list[CandidateCardOut] = []
    cards_total_value_eur: Decimal | None = None
    purchase: PurchaseOut | None = None


class TcgdexCardOut(BaseModel):
    id: str
    name: str
    image: str | None = None


class EvaluateCardIn(BaseModel):
    tcgdex_id: str | None = None
    name: str
    set: str | None = None
    number: str | None = None
    language: Language
    condition: Condition
    printing: Printing = Printing.NORMAL
    quantity: int = 1


class EvaluateRequest(BaseModel):
    cards: list[EvaluateCardIn]


class EvaluationResponse(BaseModel):
    total_value_eur: Decimal | None
    estimated_profit_eur: Decimal | None
    soldcomps_active: bool
    note: str | None


def _require_text(value: str) -> str:
    """§25a UStG: Erwerbsdaten must actually be filled in, not whitespace."""
    text = (value or "").strip()
    if not text:
        raise ValueError("Pflichtfeld (§25a UStG) darf nicht leer sein")
    return text


class PurchaseIn(BaseModel):
    """Kauf erfassen. Die §25a-UStG-Felder sind Pflicht (§5/§7)."""

    candidate_id: int | None = None
    price: Decimal = Field(ge=0)
    date: date
    channel: Channel
    seller_name: str = Field(max_length=255)
    seller_address: str
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = "EUR"

    @field_validator("seller_name", "seller_address")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _require_text(v)


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int | None
    price: Decimal
    date: date
    channel: Channel
    seller_name: str
    seller_address: str
    shipping_cost: Decimal
    currency: str


class SaleIn(BaseModel):
    """Verkauf erfassen. days_to_sell wird aus dem Kaufdatum berechnet."""

    price: Decimal = Field(ge=0)
    date: date
    channel: Channel
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = "EUR"


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_id: int
    price: Decimal
    date: date
    channel: Channel
    fees: Decimal
    days_to_sell: int | None
    currency: str


class InventoryItem(BaseModel):
    purchase_id: int
    title: str
    channel: Channel
    seller_name: str
    purchase_price: Decimal
    shipping_cost: Decimal
    purchase_date: date
    days_in_stock: int
    # Exit-Regel-Ampel (§7): green <45, amber 45-89 (repricen), red >=90 (abstoßen).
    exit_status: str
    exit_hint: str


class ProviderCost(BaseModel):
    provider: str
    spent_today_eur: Decimal
    budget_eur: Decimal
    disabled: bool


class CostsSummary(BaseModel):
    providers: list[ProviderCost]
    total_cost_eur: Decimal
    buy_count: int
    # Gesamtkosten / Anzahl Kandidaten mit Verdict "buy" — die Kernkennzahl (0.3).
    cost_per_fund_eur: Decimal | None


class CascadeLevelError(BaseModel):
    """Prognosefehler je Kaskadenstufe — zeigt, welche Stufe wie gut trägt."""

    cascade_level: int
    closed_deals: int
    avg_forecast_error_eur: float | None
    avg_abs_forecast_error_eur: float | None


class MarketComparison(BaseModel):
    """Was wirklich gezahlt wurde vs. was der Markt verlangt.

    Das Verhältnis ist die eigentliche Kennzahl: unter 1,0 heißt, dass echte
    Verkäufe unter dem Cardmarket-Preis liegen — dann ist ein "Schnäppchen"
    gegenüber dem Trendpreis gar keines. Gemessen, nicht geraten.
    """

    sample_size: int
    median_ratio: float | None
    mean_ratio: float | None
    median_sold_eur: float | None
    median_market_eur: float | None
    verdict: str


class CalibrationSummary(BaseModel):
    total_candidates: int
    alerts_per_channel: dict[str, int]
    unbewertbar_rate: float | None
    decisions: dict[str, int]
    decided_count: int
    decision_rate: float | None
    avg_seconds_to_decision: float | None
    closed_deals: int
    avg_forecast_error_eur: float | None
    avg_abs_forecast_error_eur: float | None
    per_cascade_level: list[CascadeLevelError] = []
    market_comparison: MarketComparison | None = None


class TermDiagnostic(BaseModel):
    term: str
    candidates: int
    share: float
    buy: int
    skip: int
    unclear: int
    undecided: int


class UnbewertbarReason(BaseModel):
    """Warum Kandidaten unbewertbar blieben, gebuendelt — die Frage, die der
    Betreiber tatsaechlich stellt ("wieso ist alles unbewertbar?")."""

    label: str
    count: int


class DiagnosticsReport(BaseModel):
    total_candidates: int
    per_term: list[TermDiagnostic]
    time_to_alert_count: int
    time_to_alert_median_seconds: float | None
    time_to_alert_p90_seconds: float | None
    # Title resolver (wired in Block 2): how often it ran vs. actually resolved.
    resolver_attempted: int
    resolver_resolved: int
    # Kandidaten, die die Automatik nie angefasst hat (z.B. aelter als die
    # Automatik, oder zur Handarbeit vorgemerkt) — kein Misserfolg.
    never_attempted: int = 0
    unbewertbar_reasons: list[UnbewertbarReason] = []


class JournalItem(BaseModel):
    purchase_id: int
    purchase_price: Decimal
    purchase_date: date
    shipping_cost: Decimal
    seller_name: str
    channel: Channel
    sale_price: Decimal
    sale_date: date
    fees: Decimal
    days_to_sell: int | None
    actual_profit: Decimal
    forecast_profit: Decimal | None
    forecast_error: Decimal | None
