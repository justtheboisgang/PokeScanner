"""ReferenceValueCascade orchestrator (§6).

Ties the SoldComps + TCGdex clients to the pure cascade. This is a transparent
wire: the *language-bucketing policy* from §4.2 ("erst ohne Filter abfragen, nur
nachschärfen wenn genug Treffer da sind") is deliberately NOT baked in here — the
caller supplies the per-bucket aspect filters. That adaptive policy belongs to
Phase 2, where it is actually exercised on live channels. See the Phase 1 review
notes: §9 (show each comp individually) will additionally require persisting comps,
which the §5 data model does not yet include.
"""

from __future__ import annotations

from datetime import datetime

from app.clients.soldcomps import SoldCompsClient
from app.clients.tcgdex import CardmarketPricing, TCGdexClient
from app.models.card import Card, Variant
from app.models.enums import Language
from app.models.reference_comp import ReferenceComp
from app.models.reference_value import ReferenceValue
from app.pricing.adapters import sold_items_to_comps
from app.pricing.cascade import (
    CascadeConfig,
    ReferenceResult,
    select_reference_value,
    within_window,
)

# Localized language facet names (§4.2: Facettennamen sind pro Site lokalisiert).
# Defaults for ebay.de; override per call as needed.
DEFAULT_DE_ASPECT = {"Sprache": "Deutsch"}
DEFAULT_EN_ASPECT = {"Sprache": "Englisch"}


def build_query(card: Card) -> str:
    """Build a sold-comp search query from card identity."""
    parts = [card.name]
    if card.number:
        parts.append(card.number)
    return " ".join(p for p in parts if p).strip()


class ReferenceValueCascade:
    def __init__(
        self,
        soldcomps: SoldCompsClient,
        tcgdex: TCGdexClient,
        config: CascadeConfig | None = None,
    ) -> None:
        self.soldcomps = soldcomps
        self.tcgdex = tcgdex
        self.config = config or CascadeConfig.from_settings()

    def _cardmarket(self, card: Card) -> CardmarketPricing | None:
        if not card.tcgdex_id:
            return None
        return self.tcgdex.get_cardmarket_pricing(card.tcgdex_id)

    def compute(
        self,
        card: Card,
        variant: Variant,
        *,
        query: str | None = None,
        de_aspect_filter: dict | None = None,
        en_aspect_filter: dict | None = None,
        seller_type: str | None = None,
        now: datetime | None = None,
    ) -> ReferenceResult:
        """Run the full cascade for one variant."""
        query = query or build_query(card)

        # Same-language bucket (the variant's own language).
        same_aspect = (
            de_aspect_filter if variant.language == Language.DE else en_aspect_filter
        )
        same_raw = self.soldcomps.scrape_sold(
            query, seller_type=seller_type, aspect_filter=same_aspect
        )
        comps_same = within_window(
            sold_items_to_comps(same_raw, language=variant.language),
            self.config.window_days,
            now=now,
        )

        # English bucket only matters for a German variant (Stufe 3).
        comps_english: list = []
        if variant.language == Language.DE:
            en_raw = self.soldcomps.scrape_sold(
                query, seller_type=seller_type, aspect_filter=en_aspect_filter
            )
            comps_english = within_window(
                sold_items_to_comps(en_raw, language=Language.EN),
                self.config.window_days,
                now=now,
            )

        return select_reference_value(
            variant_language=variant.language,
            variant_condition=variant.condition,
            variant_printing=variant.printing,
            comps_same_lang=comps_same,
            comps_english=comps_english,
            cardmarket=self._cardmarket(card),
            config=self.config,
        )


def persist_reference_value(
    session, variant_id: int, result: ReferenceResult
) -> ReferenceValue | None:
    """Persist a valuable result (Stufe 1-4) and its comps. Stufe 5 stores nothing.

    Each comp is stored individually so the website can show every data point
    behind the reference value (§9).
    """
    if not result.is_valuable or result.source is None:
        return None
    rv = ReferenceValue(
        variant_id=variant_id,
        value=result.value,
        currency=result.currency,
        source=result.source,
        cascade_level=result.cascade_level,
        sample_size=result.sample_size,
        is_weak=result.is_weak,
    )
    rv.comps = [
        ReferenceComp(
            price=c.price,
            currency=c.currency,
            sold_at=c.sold_at,
            language=c.language,
            condition=c.condition,
            boa_hydrated=c.boa_hydrated,
            epid=c.epid,
            source_item_id=c.source_item_id,
        )
        for c in result.comps
    ]
    session.add(rv)
    return rv
