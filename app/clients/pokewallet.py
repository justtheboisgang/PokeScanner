"""PokeWallet client — Marktpreise (Angebotsseite), NICHT echte Verkäufe.

Die Unterscheidung ist der Kern des ganzen Systems (§4.2/§6):

  * SoldComps liefert, was tatsächlich **gezahlt** wurde — abgeschlossene
    Geschäfte. Das ist die Wahrheit, auf der die Kaskade Stufe 1-3 steht.
  * PokeWallet liefert, was Karten **kosten sollen** — Cardmarket-Trend und
    TCGPlayer-Marktpreis. Angebotsseite, und bei Vintage regelmäßig über dem,
    was wirklich gezahlt wird.

Deshalb speist PokeWallet nur Stufe 4 (schwach) — und wird ansonsten *neben*
dem echten Verkaufswert festgehalten, damit die Lücke zwischen beiden messbar
wird, statt geraten zu werden.

Währungen werden NIE vermischt: Cardmarket ist EUR, TCGPlayer USD. Nur die
EUR-Seite darf in eine Bewertung einfließen (keine Umrechnung, §6).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.clients.exceptions import ClientError, RateLimitError
from app.config import get_settings

logger = logging.getLogger(__name__)


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out > 0 else None


@dataclass(frozen=True)
class MarketPricing:
    """Ask-side snapshot for one card variant. Never a sold price."""

    # Cardmarket (EUR) — the only side that may feed a valuation.
    cm_avg: Decimal | None = None
    cm_low: Decimal | None = None
    cm_trend: Decimal | None = None
    cm_avg7: Decimal | None = None
    cm_avg30: Decimal | None = None
    # TCGPlayer (USD) — display and analysis only, never converted.
    tcg_market_usd: Decimal | None = None
    tcg_low_usd: Decimal | None = None
    # Provenance.
    card_id: str | None = None
    card_name: str | None = None
    set_name: str | None = None
    variant: str | None = None

    @property
    def has_eur(self) -> bool:
        return any(
            v is not None
            for v in (self.cm_trend, self.cm_avg, self.cm_avg7, self.cm_avg30)
        )

    def best_eur(self) -> Decimal | None:
        """The most representative EUR figure, in order of usefulness.

        avg7 first: a seven-day average is steadier than the raw trend and far
        less jumpy than a single low offer.
        """
        for value in (self.cm_avg7, self.cm_trend, self.cm_avg, self.cm_avg30):
            if value is not None:
                return value
        return None


class PokeWalletClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        min_interval: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.pokewallet_api_key
        self.base_url = (base_url or settings.pokewallet_base_url).rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            transport=transport,
            timeout=timeout,
            headers={"X-API-Key": self.api_key} if self.api_key else {},
        )
        # Free tier is 100 requests/hour. Spacing them out keeps us under it
        # without having to track a window.
        self._min_interval = (
            settings.pokewallet_min_interval_seconds
            if min_interval is None
            else min_interval
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        # Count requests so the cost guard can record usage like any provider.
        self.request_count = 0
        self.remaining_day: int | None = None

    def __enter__(self) -> "PokeWalletClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _throttle(self) -> None:
        if self._min_interval <= 0 or self._last_request_at is None:
            return
        wait = self._min_interval - (self._monotonic() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)

    def _get(self, path: str, params: dict) -> dict:
        self._throttle()
        self.request_count += 1
        try:
            resp = self._client.get(path, params=params)
        finally:
            self._last_request_at = self._monotonic()

        remaining = resp.headers.get("X-RateLimit-Remaining-Day")
        if remaining is not None:
            try:
                self.remaining_day = int(remaining)
            except ValueError:
                pass

        if resp.status_code == 429:
            raise RateLimitError("PokeWallet rate limit exceeded")
        if resp.status_code >= 400:
            raise ClientError(
                f"PokeWallet error {resp.status_code} on {path}: {resp.text[:300]}"
            )
        body = resp.json()
        return body if isinstance(body, dict) else {}

    # -- public ------------------------------------------------------------

    def search(self, query: str, *, limit: int = 5) -> list[dict]:
        """Raw search results. PokeWallet accepts names and "63/102" numbers."""
        if not self.enabled or not query.strip():
            return []
        body = self._get("/search", {"q": query.strip(), "limit": limit})
        results = body.get("results")
        return list(results) if isinstance(results, list) else []

    def pricing_for(
        self, name: str, number: str | None = None, *, prefer_holo: bool = False
    ) -> MarketPricing | None:
        """Market snapshot for a card, or None when nothing matches.

        `number` may be the full "63/102" — PokeWallet handles that form, and it
        narrows the search to the right print far better than the name alone.
        """
        query = f"{name} {number}".strip() if number else name.strip()
        try:
            results = self.search(query, limit=5)
        except RateLimitError:
            raise
        except Exception:
            logger.warning("pokewallet lookup failed for %r", query, exc_info=True)
            return None
        if not results:
            return None
        return self._to_pricing(results[0], prefer_holo=prefer_holo)

    @staticmethod
    def _pick_cm_variant(prices: list, prefer_holo: bool) -> dict | None:
        wanted = "holo" if prefer_holo else "normal"
        fallback: dict | None = None
        for entry in prices:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("variant_type", "")).lower() == wanted:
                return entry
            fallback = fallback or entry
        return fallback

    @staticmethod
    def _pick_tcg_variant(prices: list, prefer_holo: bool) -> dict | None:
        wanted = "holofoil" if prefer_holo else "normal"
        fallback: dict | None = None
        for entry in prices:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("sub_type_name", "")).lower() == wanted:
                return entry
            fallback = fallback or entry
        return fallback

    @classmethod
    def _to_pricing(cls, result: dict, *, prefer_holo: bool) -> MarketPricing:
        info = result.get("card_info") or {}
        cm = result.get("cardmarket") or {}
        tcg = result.get("tcgplayer") or {}
        cm_entry = cls._pick_cm_variant(cm.get("prices") or [], prefer_holo) or {}
        tcg_entry = cls._pick_tcg_variant(tcg.get("prices") or [], prefer_holo) or {}
        return MarketPricing(
            cm_avg=_dec(cm_entry.get("avg")),
            cm_low=_dec(cm_entry.get("low")),
            cm_trend=_dec(cm_entry.get("trend")),
            cm_avg7=_dec(cm_entry.get("avg7")),
            cm_avg30=_dec(cm_entry.get("avg30")),
            tcg_market_usd=_dec(tcg_entry.get("market_price")),
            tcg_low_usd=_dec(tcg_entry.get("low_price")),
            card_id=(str(result["id"]) if result.get("id") else None),
            card_name=(str(info["name"]) if info.get("name") else None),
            set_name=(str(info["set_name"]) if info.get("set_name") else None),
            variant=(
                str(cm_entry.get("variant_type"))
                if cm_entry.get("variant_type")
                else None
            ),
        )
