"""Bestehende Kandidaten nachbewerten (Diagnose + Nachziehen).

Die automatische Bewertung läuft sonst nur bei NEUEN Treffern. Nach einer
Änderung am Resolver oder nach dem Setzen eines Schlüssels sitzen die bereits
gespeicherten Kandidaten aber unbewertet in der Datenbank — und genau an denen
will man sehen, ob die Kaskade brauchbare Werte liefert.

    docker compose run --rm worker python -m app.revalue            # 5 Stueck
    docker compose run --rm worker python -m app.revalue --limit 20
    docker compose run --rm worker python -m app.revalue --dry-run  # kostenlos

Jede Bewertung kostet Geld (SoldComps), deshalb ist das Limit klein und muss
bewusst erhöht werden. Der Kosten-Wächter und die Nachschlagschwelle greifen
unverändert.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.clients.pokewallet import PokeWalletClient
from app.clients.tcgdex import TCGdexClient
from app.config import get_settings
from app.db import session_scope
from app.models.candidate import Candidate
from app.models.enums import Language
from app.models.market_snapshot import MarketSnapshot
from app.pricing.evaluate import auto_value_candidate
from app.pricing.resolver import SingleCardTitleResolver

logger = logging.getLogger(__name__)


def _resolver(settings) -> SingleCardTitleResolver:
    lang = Language.DE if settings.tcgdex_primary_lang == "de" else Language.EN
    return SingleCardTitleResolver(TCGdexClient(), lang=lang)


def run(limit: int = 5, dry_run: bool = False) -> None:
    settings = get_settings()
    resolver = _resolver(settings)
    pokewallet = PokeWalletClient() if settings.pokewallet_api_key else None

    valued = 0
    skipped = 0
    with session_scope() as session:
        candidates = session.scalars(
            select(Candidate)
            .where(Candidate.reference_value_id.is_(None))
            .options(joinedload(Candidate.listing))
            .order_by(Candidate.id.desc())
            .limit(limit)
        ).unique().all()

        if not candidates:
            print("Keine unbewerteten Kandidaten gefunden.")
            return

        print(f"\n=== {len(candidates)} Kandidaten werden nachbewertet ===")
        if dry_run:
            print("(Trockenlauf: nur Auflösung, keine kostenpflichtige Bewertung)\n")

        for cand in candidates:
            listing = cand.listing
            if listing is None:
                continue
            price = f"{listing.price} {listing.currency}" if listing.price else "—"
            print(f"\n  #{cand.id}  {listing.title}")
            print(f"    Preis: {price}")

            if dry_run:
                resolved = resolver.resolve(listing.title, listing.description)
                print(
                    f"    {'aufgelöst: ' + resolved.name + ' ' + (resolved.number or '')}"
                    if resolved
                    else "    nicht auflösbar -> unbewertbar"
                )
                skipped += 1
                continue

            try:
                result = auto_value_candidate(
                    session,
                    cand,
                    resolver=resolver,
                    settings=settings,
                    pokewallet=pokewallet,
                )
            except Exception as exc:  # noqa: BLE001 — Diagnose bricht nie ab
                print(f"    FEHLER: {exc!r}")
                skipped += 1
                continue

            session.flush()
            session.refresh(cand)
            rv = cand.reference_value
            if rv is not None:
                weak = " (schwach)" if rv.is_weak else ""
                print(
                    f"    BEWERTET: {rv.value} {rv.currency} | Stufe {rv.cascade_level}"
                    f" | n={rv.sample_size}{weak}"
                )
                if cand.estimated_profit is not None:
                    print(f"    Gesch. Gewinn: {cand.estimated_profit} EUR")
                snap = session.scalar(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.reference_value_id == rv.id)
                    .limit(1)
                )
                if snap is not None:
                    market = snap.cm_avg7 or snap.cm_trend or snap.cm_avg
                    if market:
                        ratio = float(rv.value) / float(market)
                        print(
                            f"    Marktpreis: {market} EUR  ->  verkauft/Markt = "
                            f"{ratio:.0%}"
                        )
                valued += 1
            else:
                print(f"    unbewertbar{' — ' + result.note if result.note else ''}")
                skipped += 1

    print(f"\n=== {valued} bewertet, {skipped} nicht bewertet ===\n")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Bestehende Kandidaten nachbewerten")
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Wie viele Kandidaten (Default 5 — jede Bewertung kostet Geld)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nur auflösen, nichts bewerten (kostenlos)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    run(limit=max(1, args.limit), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
