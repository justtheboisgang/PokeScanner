"""TCGdex client (§4.1).

Metadata + embedded Cardmarket/TCGplayer pricing. No API key, no documented rate
limits. Two things this client must get right:

  * a card that is not listed on a marketplace has its provider block MISSING
    entirely — never assume `pricing` (or a sub-block) exists;
  * not every card exists in German — fall back to `en` per card.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class CardmarketPricing:
    """Cardmarket block (EUR, daily). Any field may be None if TCGdex omitted it."""

    avg: Decimal | None = None
    low: Decimal | None = None
    trend: Decimal | None = None
    avg1: Decimal | None = None
    avg7: Decimal | None = None
    avg30: Decimal | None = None
    # Holo variants.
    avg_holo: Decimal | None = None
    low_holo: Decimal | None = None
    trend_holo: Decimal | None = None
    avg7_holo: Decimal | None = None
    avg30_holo: Decimal | None = None


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_cardmarket(block: dict) -> CardmarketPricing:
    return CardmarketPricing(
        avg=_to_decimal(block.get("avg")),
        low=_to_decimal(block.get("low")),
        trend=_to_decimal(block.get("trend")),
        avg1=_to_decimal(block.get("avg1")),
        avg7=_to_decimal(block.get("avg7")),
        avg30=_to_decimal(block.get("avg30")),
        avg_holo=_to_decimal(block.get("avg-holo")),
        low_holo=_to_decimal(block.get("low-holo")),
        trend_holo=_to_decimal(block.get("trend-holo")),
        avg7_holo=_to_decimal(block.get("avg7-holo")),
        avg30_holo=_to_decimal(block.get("avg30-holo")),
    )


class TCGdexClient:
    def __init__(
        self,
        base_url: str | None = None,
        primary_lang: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.tcgdex_base_url).rstrip("/")
        self.primary_lang = primary_lang or settings.tcgdex_primary_lang
        self._client = httpx.Client(
            base_url=self.base_url, transport=transport, timeout=timeout
        )
        self._sets_cache: dict[str, list[dict]] = {}

    def __enter__(self) -> "TCGdexClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search_cards(
        self, query: str, lang: str | None = None, *, limit: int = 100
    ) -> list[dict]:
        """Search cards by name. Returns brief card dicts.

        Uses TCGdex filtering (`?name=like:<q>`); falls back to an empty list on
        error. Each item has at least `id` and `name` (and usually `image`).

        The limit is deliberately generous: a popular Pokemon appears in dozens
        of sets, and a short list silently cuts off the very card being looked
        for. "Bisaflor 15/102" failed exactly that way — Base Set was not among
        the first 15 results, so the number never matched anything.
        """
        lang = lang or self.primary_lang
        query = query.strip()
        if not query:
            return []
        resp = self._client.get(
            f"/{lang}/cards",
            params={"name": f"like:{query}", "pagination:itemsPerPage": limit},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return list(data)[:limit] if isinstance(data, list) else []

    def get_sets(self, lang: str | None = None) -> list[dict]:
        """All sets with their card counts. Cached — the list barely changes.

        Needed to read the denominator of a card number: "2/102" means a set
        with 102 cards, which tells Base Set apart from every other set that
        also has a card number 2.
        """
        lang = lang or self.primary_lang
        cached = self._sets_cache.get(lang)
        if cached is not None:
            return cached
        resp = self._client.get(f"/{lang}/sets")
        if resp.status_code == 404:
            self._sets_cache[lang] = []
            return []
        resp.raise_for_status()
        data = resp.json()
        sets = list(data) if isinstance(data, list) else []
        self._sets_cache[lang] = sets
        return sets

    def set_sizes(self, lang: str | None = None) -> dict[str, int]:
        """Map set id -> official card count ("102" in "2/102")."""
        sizes: dict[str, int] = {}
        for item in self.get_sets(lang):
            set_id = item.get("id")
            count = item.get("cardCount")
            if isinstance(count, dict):
                count = count.get("official") or count.get("total")
            if set_id and isinstance(count, int) and count > 0:
                sizes[str(set_id)] = count
        return sizes

    def get_card(self, card_id: str, lang: str | None = None) -> dict | None:
        """Fetch one card. Returns None on 404 (card not in that language)."""
        lang = lang or self.primary_lang
        resp = self._client.get(f"/{lang}/cards/{card_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_card_with_fallback(self, card_id: str) -> tuple[dict | None, str | None]:
        """Try the primary language, then fall back to English (§4.1).

        Returns (card_dict, resolved_lang) or (None, None) if not found at all.
        """
        card = self.get_card(card_id, self.primary_lang)
        if card is not None:
            return card, self.primary_lang
        if self.primary_lang != "en":
            card = self.get_card(card_id, "en")
            if card is not None:
                return card, "en"
        return None, None

    def get_cardmarket_pricing(
        self, card_id: str, lang: str | None = None
    ) -> CardmarketPricing | None:
        """Return the Cardmarket block, or None if pricing/cardmarket is absent."""
        card = self.get_card(card_id, lang)
        if card is None:
            return None
        pricing = card.get("pricing")
        if not isinstance(pricing, dict):
            return None
        cardmarket = pricing.get("cardmarket")
        if not isinstance(cardmarket, dict):
            return None
        return _parse_cardmarket(cardmarket)
