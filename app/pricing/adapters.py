"""Adapters: normalize raw SoldComps items into ReferenceComp (§6).

Kept separate from the client (thin transport) and from the pure cascade
(no I/O), so parsing quirks are isolated and unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.models.enums import Condition, Language
from app.pricing.cascade import ReferenceComp

# Item-specifics keys that may carry the condition (site-localized).
_CONDITION_KEYS = ("Zustand", "Condition", "condition")

# Best-effort free-text -> Condition. Conservative: anything unrecognized stays
# UNKNOWN (which pushes the comp to Stufe 2 rather than faking a Stufe 1 match).
_CONDITION_TEXT: dict[str, Condition] = {
    "mint": Condition.MINT,
    "gem mint": Condition.MINT,
    "near mint": Condition.NEAR_MINT,
    "nm": Condition.NEAR_MINT,
    "neuwertig": Condition.NEAR_MINT,
    "excellent": Condition.EXCELLENT,
    "hervorragend": Condition.EXCELLENT,
    "good": Condition.GOOD,
    "gut": Condition.GOOD,
    "light played": Condition.LIGHT_PLAYED,
    "leicht gespielt": Condition.LIGHT_PLAYED,
    "played": Condition.PLAYED,
    "gespielt": Condition.PLAYED,
    "bespielt": Condition.PLAYED,
    "moderately played": Condition.PLAYED,
    "poor": Condition.POOR,
    "schlecht": Condition.POOR,
    "heavily played": Condition.POOR,
    "stark gespielt": Condition.POOR,
}


def parse_condition(text: str | None) -> Condition:
    if not text:
        return Condition.UNKNOWN
    return _CONDITION_TEXT.get(text.strip().lower(), Condition.UNKNOWN)


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        # Some APIs nest as {"value": "12.34", "currency": "EUR"}.
        value = value.get("value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Epoch seconds or milliseconds.
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _extract_condition(item: dict) -> Condition:
    specifics = item.get("itemSpecifics")
    if isinstance(specifics, dict):
        for key in _CONDITION_KEYS:
            if key in specifics:
                return parse_condition(str(specifics[key]))
    for key in _CONDITION_KEYS:
        if key in item:
            return parse_condition(str(item[key]))
    return Condition.UNKNOWN


def sold_item_to_comp(
    item: dict, *, language: Language, currency: str = "EUR"
) -> ReferenceComp | None:
    """Convert one raw sold item to a ReferenceComp. None if no usable price."""
    price = _to_decimal(item.get("soldPrice"))
    if price is None or price <= 0:
        return None

    sold_at = _parse_datetime(
        item.get("soldDate") or item.get("dateSold") or item.get("soldAt")
    )
    return ReferenceComp(
        price=price,
        currency=currency,
        sold_at=sold_at,
        language=language,
        condition=_extract_condition(item),
        boa_hydrated=bool(item.get("boaHydrated", False)),
        epid=(str(item["epid"]) if item.get("epid") is not None else None),
        source_item_id=(
            str(item["itemId"]) if item.get("itemId") is not None else None
        ),
    )


def sold_items_to_comps(
    items: list[dict], *, language: Language, currency: str = "EUR"
) -> list[ReferenceComp]:
    comps: list[ReferenceComp] = []
    for item in items:
        comp = sold_item_to_comp(item, language=language, currency=currency)
        if comp is not None:
            comps.append(comp)
    return comps
