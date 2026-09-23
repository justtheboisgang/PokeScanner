"""Auktions-Wache: melden, wenn eine Auktion gleich endet und zu billig ist.

Der Ablauf ist bewusst zweigeteilt, weil beides verschiedene Anforderungen hat:

    scan()  laeuft alle paar Minuten, sucht Auktionen, die innerhalb des
            Fensters enden, loest den Titel auf und holt EINMAL den
            Vergleichswert. Das darf dauern.
    tick()  laeuft jede Minute, nimmt die Auktionen, die in wenigen Minuten
            enden, holt den AKTUELLEN Gebotsstand und meldet, wenn er weit
            genug unter dem Vergleichswert liegt. Das muss schnell sein.

Warum nicht einfach beim Fund melden? Weil der Preis einer Auktion bis zum
Schluss steigt. Eine Meldung dreissig Minuten vor Ende sagt nichts ueber den
Preis, zu dem die Karte tatsaechlich weggeht.

Der Vergleichswert kommt aus MARKTPREISEN (PokeWallet/Cardmarket), nicht aus
Verkaufsdaten. Zwei Gruende: er ist sofort da, und er kostet nichts. Das ist
zugleich die Grenze dieser Funktion — ein Marktpreis ist eine Forderung, kein
erzielter Preis, und steht so auch in der Meldung.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.alerts.discord import AlertContent, DiscordNotifier
from app.clients.ebay import EbayBrowseClient
from app.clients.pokewallet import PokeWalletClient
from app.clients.tcgdex import TCGdexClient
from app.config import Settings, get_settings
from app.config_data import load_search_terms
from app.db import session_scope
from app.models.auction_watch import AuctionWatch
from app.models.enums import Language, Printing
from app.pricing.resolver import SingleCardTitleResolver

logger = logging.getLogger(__name__)


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _price_of(item: dict) -> tuple[Decimal | None, str]:
    """Der aktuelle Gebotsstand, nicht der Sofortkauf-Preis."""
    for key in ("currentBidPrice", "price"):
        block = item.get(key)
        if isinstance(block, dict) and block.get("value") is not None:
            return _decimal(block.get("value")), str(block.get("currency") or "EUR")
    return None, "EUR"


def _ends_at(item: dict) -> datetime | None:
    raw = item.get("itemEndDate")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    """Zeitzone anheften, falls die Datenbank sie verloren hat.

    Postgres liefert die Zeitzone zurueck, SQLite (Tests) nicht. Ohne diese
    Angleichung scheitert jeder Vergleich mit "jetzt" — und die Wache haengt
    genau an solchen Vergleichen.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _image(item: dict) -> str | None:
    image = item.get("image")
    if isinstance(image, dict) and image.get("imageUrl"):
        return str(image["imageUrl"])
    return None


class AuctionWatcher:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        ebay: EbayBrowseClient | None = None,
        pokewallet: PokeWalletClient | None = None,
        resolver: SingleCardTitleResolver | None = None,
        notifier: DiscordNotifier | None = None,
        session_factory=session_scope,
        now=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.settings = settings or get_settings()
        self.ebay = ebay
        self.pokewallet = pokewallet
        self.resolver = resolver
        self.notifier = notifier or DiscordNotifier()
        self.session_factory = session_factory
        self.now = now

    # -- Einrichtung -------------------------------------------------------

    def _client(self) -> EbayBrowseClient:
        if self.ebay is None:
            self.ebay = EbayBrowseClient()
        return self.ebay

    def _resolver(self) -> SingleCardTitleResolver:
        if self.resolver is None:
            lang = (
                Language.DE
                if self.settings.tcgdex_primary_lang == "de"
                else Language.EN
            )
            self.resolver = SingleCardTitleResolver(TCGdexClient(), lang=lang)
        return self.resolver

    def _wallet(self) -> PokeWalletClient | None:
        if self.pokewallet is None and self.settings.pokewallet_api_key:
            self.pokewallet = PokeWalletClient()
        return self.pokewallet

    # -- Takt 1: finden und bewerten ---------------------------------------

    def scan(self) -> int:
        """Bald endende Auktionen erfassen und einmalig bewerten."""
        if not self.settings.auction_watch_enabled:
            return 0
        terms = load_search_terms().active
        found = 0
        client = self._client()
        for term in terms:
            try:
                items = client.search_auctions(
                    term,
                    ending_within_minutes=self.settings.auction_window_minutes,
                    limit=self.settings.ebay_browse_limit,
                    now=self.now(),
                )
            except Exception:
                logger.warning("auction search failed for %r", term, exc_info=True)
                continue
            for item in items:
                if self._store(item, term):
                    found += 1
        logger.info("auction scan: %d neue Auktionen im Fenster", found)
        return found

    def _store(self, item: dict, term: str) -> bool:
        external_id = item.get("itemId") or item.get("legacyItemId")
        title = item.get("title")
        ends_at = _ends_at(item)
        if not external_id or not title or ends_at is None:
            return False
        price, currency = _price_of(item)

        with self.session_factory() as session:
            existing = session.scalar(
                select(AuctionWatch).where(
                    AuctionWatch.external_id == str(external_id)
                )
            )
            if existing is not None:
                existing.current_price = price
                existing.ends_at = ends_at
                return False

            watch = AuctionWatch(
                external_id=str(external_id),
                title=str(title),
                url=item.get("itemWebUrl"),
                image=_image(item),
                currency=currency,
                ends_at=ends_at,
                current_price=price,
                matched_search_term=term,
            )
            self._value(watch)
            session.add(watch)
            return True

    def _value(self, watch: AuctionWatch) -> None:
        """Vergleichswert bestimmen — einmal, in Ruhe, lange vor dem Ende."""
        resolved = self._resolver().resolve(watch.title, None)
        if resolved is None:
            watch.skip_reason = "Titel nicht auf genau eine Karte auflösbar"
            return
        watch.card_name = resolved.name
        watch.card_number = resolved.number
        if resolved.card_language is not None and resolved.card_language not in (
            "de",
            "en",
        ):
            watch.skip_reason = (
                f"Sprache '{resolved.card_language}' — kein belastbarer "
                "Vergleichsfaktor"
            )
            return
        wallet = self._wallet()
        if wallet is None or not wallet.enabled:
            watch.skip_reason = "kein Marktpreis verfügbar (PokeWallet nicht aktiv)"
            return
        try:
            market = wallet.pricing_for(
                resolved.name,
                resolved.number,
                prefer_holo=resolved.printing
                in (Printing.HOLO, Printing.REVERSE_HOLO),
            )
        except Exception:
            logger.warning("pokewallet failed for %s", resolved.name, exc_info=True)
            watch.skip_reason = "Marktpreis-Abruf fehlgeschlagen"
            return
        value = market.best_eur() if market is not None else None
        if value is None:
            watch.skip_reason = "kein Marktpreis in EUR gefunden"
            return
        watch.reference_value_eur = value
        watch.reference_source = "pokewallet"

    # -- Takt 2: kurz vor Schluss vergleichen ------------------------------

    def tick(self) -> int:
        """Auktionen kurz vor Ablauf pruefen und ggf. melden."""
        if not self.settings.auction_watch_enabled:
            return 0
        now = self.now()
        lead = timedelta(minutes=self.settings.auction_alert_lead_minutes)
        # Ein Fenster statt eines Zeitpunkts: der Takt laeuft minuetlich, und
        # eine Auktion darf nicht durchrutschen, nur weil die Sekunde nicht
        # genau passt.
        horizon = now + lead + timedelta(minutes=1)
        sent = 0
        with self.session_factory() as session:
            open_watches = session.scalars(
                select(AuctionWatch).where(
                    AuctionWatch.alerted_at.is_(None),
                    AuctionWatch.reference_value_eur.is_not(None),
                )
            ).all()
            # Die Zeitgrenze wird in Python gezogen, nicht in SQL: die
            # Datenbanken gehen unterschiedlich mit Zeitzonen um, und die
            # Menge ist klein (nur Auktionen im Fenster).
            for watch in open_watches:
                ends_at = _aware(watch.ends_at)
                if not (now < ends_at <= horizon):
                    continue
                if self._check(watch, now, ends_at):
                    sent += 1
        return sent

    def _check(
        self, watch: AuctionWatch, now: datetime, ends_at: datetime | None = None
    ) -> bool:
        ends_at = ends_at or _aware(watch.ends_at)
        item = None
        try:
            item = self._client().get_item(watch.external_id)
        except Exception:
            logger.warning(
                "auction refresh failed for %s", watch.external_id, exc_info=True
            )
        if item is not None:
            price, currency = _price_of(item)
            if price is not None:
                watch.current_price = price
                watch.currency = currency
        watch.checked_at = now

        price = watch.current_price
        value = watch.reference_value_eur
        if price is None or value is None or value <= 0:
            return False
        discount = (value - price) / value * 100
        if discount < self.settings.auction_min_discount_pct:
            return False

        minutes_left = max(0, int((ends_at - now).total_seconds() // 60))
        content = AlertContent(
            title=f"⏳ Auktion endet in {minutes_left} min — {watch.title}",
            url=watch.url,
            price=price,
            currency=watch.currency,
            location=None,
            channel="eBay-Auktion",
            matched_search_term=watch.matched_search_term,
            image_url=watch.image,
            profit_text=(
                f"{discount:.0f}% unter Marktpreis ({value} EUR) — "
                f"{watch.card_name or 'Karte'} {watch.card_number or ''}"
            ),
            cascade_text=(
                "Marktpreis (Angebotspreis, kein erzielter Preis). Gebote "
                "können in den letzten Sekunden noch steigen; Versand ist "
                "nicht eingerechnet."
            ),
        )
        try:
            self.notifier.send(content)
        except Exception:
            logger.exception("auction alert failed for %s", watch.external_id)
            return False
        watch.alerted_at = now
        logger.info(
            "auction alert: %s bei %s EUR (%.0f%% unter %s EUR)",
            watch.title[:60],
            price,
            discount,
            value,
        )
        return True


def main(argv: list[str] | None = None) -> None:
    """Beide Takte einmal von Hand ausfuehren (Diagnose)."""
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Auktions-Wache einmal ausführen")
    parser.add_argument("--nur-suchen", action="store_true", dest="scan_only")
    parser.add_argument("--nur-pruefen", action="store_true", dest="tick_only")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    watcher = AuctionWatcher()
    if not args.tick_only:
        print(f"Gefunden: {watcher.scan()} neue Auktionen im Fenster")
    if not args.scan_only:
        print(f"Gemeldet: {watcher.tick()} Auktionen kurz vor Ablauf")


if __name__ == "__main__":
    main()
