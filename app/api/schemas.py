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


class CandidateDetail(BaseModel):
    id: int
    listing: ListingOut
    estimated_profit: Decimal | None
    alert_reason: str | None
    matched_search_term: str | None
    alert_sent_at: datetime | None
    reference_value: ReferenceValueOut | None
    decision: DecisionOut | None


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
