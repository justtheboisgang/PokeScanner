"""Pydantic schemas for the web API (§9)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    Channel,
    Condition,
    CounterfeitCheck,
    Language,
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


class CandidateDetail(BaseModel):
    id: int
    listing: ListingOut
    estimated_profit: Decimal | None
    alert_reason: str | None
    matched_search_term: str | None
    alert_sent_at: datetime | None
    reference_value: ReferenceValueOut | None
    decision: DecisionOut | None
    enrichment: EnrichmentOut | None


class InventoryItem(BaseModel):
    purchase_id: int
    title: str
    channel: Channel
    seller_name: str
    purchase_price: Decimal
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


class TermDiagnostic(BaseModel):
    term: str
    candidates: int
    share: float
    buy: int
    skip: int
    unclear: int
    undecided: int


class DiagnosticsReport(BaseModel):
    total_candidates: int
    per_term: list[TermDiagnostic]
    time_to_alert_count: int
    time_to_alert_median_seconds: float | None
    time_to_alert_p90_seconds: float | None
    # Title resolver (wired in Block 2): how often it ran vs. actually resolved.
    resolver_attempted: int
    resolver_resolved: int


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
