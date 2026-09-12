"""Reference-value cascade (§6).

Walks from top to bottom; the level reached is recorded (cascade_level) together
with the sample size. The system is allowed to say "unbewertbar" (R3): if the
data is too thin, no value is invented — Stufe 5 returns value=None and the alert
still fires downstream (R4).

    Stufe 1: SoldComps, ebay.de, sold=true, hydrateBoa=true, matching language,
             matching condition            -> median if sample_size >= N
    Stufe 2: as 1 but all conditions       -> median * condition_factor
    Stufe 3: English comps (market ebay.de, EUR, no FX in V1)
                                            -> median * language_factor
    Stufe 4: TCGdex Cardmarket trend / avg7 -> marked as a weak reference
    Stufe 5: NO VALUE (unbewertbar)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from statistics import median as _stat_median

from app.clients.tcgdex import CardmarketPricing
from app.config import get_settings
from app.models.enums import Condition, Language, Printing, ReferenceSource

_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    """Quantize to 2 decimals (currency)."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def median_price(comps: list["ReferenceComp"]) -> Decimal:
    """Median of comp prices. Caller must ensure the list is non-empty."""
    if not comps:
        raise ValueError("median_price requires at least one comp")
    return _q(Decimal(str(_stat_median([c.price for c in comps]))))


@dataclass(frozen=True)
class ReferenceComp:
    """A single normalized sold comp (one row behind a reference value).

    `language` is assigned by which query produced the comp (the ebay.de market
    query bucket), not parsed from the item. `condition` is best-effort from the
    item specifics and defaults to UNKNOWN — which is why, in C2C reality, most
    comps land on Stufe 2 rather than Stufe 1.
    """

    price: Decimal
    currency: str
    sold_at: datetime | None
    language: Language
    condition: Condition
    boa_hydrated: bool
    epid: str | None = None
    source_item_id: str | None = None


@dataclass(frozen=True)
class ReferenceResult:
    """Outcome of the cascade. `value is None` == unbewertbar (Stufe 5)."""

    value: Decimal | None
    currency: str
    source: ReferenceSource | None
    cascade_level: int
    sample_size: int
    is_weak: bool
    comps: tuple[ReferenceComp, ...] = ()

    @property
    def is_valuable(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class CascadeConfig:
    min_sample_size: int
    window_days: int
    condition_factor: Decimal
    language_factor: Decimal

    @classmethod
    def from_settings(cls) -> "CascadeConfig":
        s = get_settings()
        return cls(
            min_sample_size=s.cascade_min_sample_size,
            window_days=s.cascade_window_days,
            condition_factor=Decimal(str(s.cascade_condition_factor)),
            language_factor=Decimal(str(s.cascade_language_factor)),
        )


def within_window(
    comps: list[ReferenceComp], window_days: int, *, now: datetime | None = None
) -> list[ReferenceComp]:
    """Keep comps sold within the window.

    Comps with an unknown sold date are KEPT (R4: großzügig, Recall über Precision)
    — the client-side soldAfter filter saves no quota anyway (§4.2.6).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    kept: list[ReferenceComp] = []
    for c in comps:
        if c.sold_at is None:
            kept.append(c)
            continue
        sold_at = c.sold_at
        if sold_at.tzinfo is None:
            sold_at = sold_at.replace(tzinfo=timezone.utc)
        if sold_at >= cutoff:
            kept.append(c)
    return kept


def _cardmarket_reference(
    cardmarket: CardmarketPricing, printing: Printing
) -> Decimal | None:
    """Stufe 4 value: Cardmarket trend, else avg7. Holo-aware by variant printing."""
    holo = printing in (Printing.HOLO, Printing.REVERSE_HOLO)
    if holo:
        for v in (cardmarket.trend_holo, cardmarket.avg7_holo):
            if v is not None:
                return v
    for v in (cardmarket.trend, cardmarket.avg7):
        if v is not None:
            return v
    return None


def select_reference_value(
    *,
    variant_language: Language,
    variant_condition: Condition,
    variant_printing: Printing,
    comps_same_lang: list[ReferenceComp],
    comps_english: list[ReferenceComp],
    cardmarket: CardmarketPricing | None,
    config: CascadeConfig,
    currency: str = "EUR",
) -> ReferenceResult:
    """Pure cascade selection over already-fetched, already-windowed comps."""
    n = config.min_sample_size

    # Stufe 1: same language, matching condition.
    s1 = [c for c in comps_same_lang if c.condition == variant_condition]
    if len(s1) >= n:
        return ReferenceResult(
            value=median_price(s1),
            currency=currency,
            source=ReferenceSource.SOLDCOMPS,
            cascade_level=1,
            sample_size=len(s1),
            is_weak=False,
            comps=tuple(s1),
        )

    # Stufe 2: same language, all conditions, times the condition factor.
    if len(comps_same_lang) >= n:
        value = _q(median_price(comps_same_lang) * config.condition_factor)
        return ReferenceResult(
            value=value,
            currency=currency,
            source=ReferenceSource.SOLDCOMPS,
            cascade_level=2,
            sample_size=len(comps_same_lang),
            is_weak=False,
            comps=tuple(comps_same_lang),
        )

    # Stufe 3: English comps times the language factor. Only when the variant is
    # German (an English variant has no DE->EN step to take).
    if variant_language == Language.DE and len(comps_english) >= n:
        value = _q(median_price(comps_english) * config.language_factor)
        return ReferenceResult(
            value=value,
            currency=currency,
            source=ReferenceSource.SOLDCOMPS,
            cascade_level=3,
            sample_size=len(comps_english),
            is_weak=False,
            comps=tuple(comps_english),
        )

    # Stufe 4: TCGdex Cardmarket — weak reference.
    if cardmarket is not None:
        cm_value = _cardmarket_reference(cardmarket, variant_printing)
        if cm_value is not None:
            return ReferenceResult(
                value=_q(cm_value),
                currency=currency,
                source=ReferenceSource.TCGDEX_CARDMARKET,
                cascade_level=4,
                sample_size=0,
                is_weak=True,
                comps=(),
            )

    # Stufe 5: no value. Unbewertbar — der Alarm geht trotzdem raus (R4).
    return ReferenceResult(
        value=None,
        currency=currency,
        source=None,
        cascade_level=5,
        sample_size=0,
        is_weak=False,
        comps=(),
    )
