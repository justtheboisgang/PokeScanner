"""Alarm rule (§7) — pure, no I/O.

Phase 2 cheap gate: a Kleinanzeigen find has no card identification, so every
qualifying listing is "unbewertbar" (cascade Stufe 5) and the alert fires anyway
(R4). The positive signal is provided by the search query itself; here we only
apply the negative list and the (default-off) price guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.config_data import SearchTerms
from app.ingest.kleinanzeigen import NormalizedListing


@dataclass(frozen=True)
class AlarmDecision:
    should_alert: bool
    reason: str


def evaluate(
    listing: NormalizedListing,
    *,
    search_terms: SearchTerms,
    price_ceiling: Decimal | None = None,
    require_price: bool = False,
) -> AlarmDecision:
    """Decide whether a normalized listing should raise an alert."""
    haystack = f"{listing.title} {listing.description or ''}"
    if search_terms.is_excluded(haystack):
        return AlarmDecision(False, "excluded: negative-list term matched")

    if require_price and listing.price is None:
        return AlarmDecision(False, "skipped: no price and require_price is on")

    if (
        price_ceiling is not None
        and listing.price is not None
        and listing.price > price_ceiling
    ):
        return AlarmDecision(False, f"skipped: price {listing.price} > ceiling {price_ceiling}")

    return AlarmDecision(True, "cheap-gate pass — unbewertbar, bitte selbst prüfen")
