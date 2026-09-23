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
from app.pricing.evaluate import auto_value_candidate, note_unresolvable
from app.pricing.resolver import SingleCardTitleResolver

logger = logging.getLogger(__name__)


def _resolver(settings) -> SingleCardTitleResolver:
    lang = Language.DE if settings.tcgdex_primary_lang == "de" else Language.EN
    return SingleCardTitleResolver(TCGdexClient(), lang=lang)


def discard_auto_valuations() -> int:
    """Automatische Bewertungen verwerfen, damit sie neu gerechnet werden.

    Noetig nach jeder Aenderung am Resolver: bestehende Werte bleiben sonst
    fuer immer stehen, auch wenn sie auf einer inzwischen korrigierten
    Aufloesung beruhen — im Feed stand so noch tagelang ein "Turtok EX XY122"
    mit dem Wert eines voellig anderen Karte.

    Von HAND identifizierte Karten bleiben unberuehrt. Die sind Arbeit des
    Betreibers und werden nicht von der Maschine weggeworfen.
    """
    from app.models.candidate_card import CandidateCard

    touched = 0
    with session_scope() as session:
        auto_links = session.scalars(
            select(CandidateCard).where(CandidateCard.source == "auto")
        ).all()
        auto_ids = {link.candidate_id for link in auto_links}
        for link in auto_links:
            session.delete(link)
        for cand in session.scalars(
            select(Candidate).where(Candidate.id.in_(auto_ids) if auto_ids else False)
        ).all():
            cand.reference_value_id = None
            cand.estimated_profit = None
            cand.valuation_attempted_at = None
            cand.valuation_note = None
            touched += 1
    return touched


def run(limit: int = 5, dry_run: bool = False) -> None:
    settings = get_settings()
    resolver = _resolver(settings)
    pokewallet = PokeWalletClient() if settings.pokewallet_api_key else None

    valued = 0
    skipped = 0
    with session_scope() as session:
        # Einen groesseren Vorrat holen: das Limit soll ECHTE Bewertungen zaehlen,
        # nicht Versuche. Sonst verpufft es an Kandidaten, die ohnehin nichts
        # kosten wuerden (nicht aufloesbar oder unter der Nachschlagschwelle) —
        # genau das passierte beim ersten Lauf.
        pool = session.scalars(
            select(Candidate)
            .where(Candidate.reference_value_id.is_(None))
            .options(joinedload(Candidate.listing))
            .order_by(Candidate.id.desc())
            .limit(max(limit * 10, 50) if not dry_run else limit)
        ).unique().all()

        if not pool:
            print("Keine unbewerteten Kandidaten gefunden.")
            return

        if dry_run:
            print(f"\n=== {len(pool)} Kandidaten werden geprüft ===")
            print("(Trockenlauf: nur Auflösung, keine kostenpflichtige Bewertung)\n")
            for cand in pool:
                listing = cand.listing
                if listing is None:
                    continue
                price = f"{listing.price} {listing.currency}" if listing.price else "—"
                print(f"\n  #{cand.id}  {listing.title}")
                print(f"    Preis: {price}")
                trace: list[str] = []
                resolved = resolver.resolve(
                    listing.title, listing.description, trace=trace
                )
                if resolved:
                    print(
                        f"    aufgelöst: {resolved.name} {resolved.number or ''}"
                    )
                    # Auch der Erfolg gehoert in die Datenbank. Sonst steht im
                    # Feed weiter nur "noch nicht bewertet", obwohl die Maschine
                    # laengst weiss, WELCHE Karte das ist — und genau das ist
                    # die Auskunft, die der Betreiber zuerst braucht.
                    # valuation_attempted_at bleibt leer: bewertet wurde nichts.
                    cand.valuation_note = (
                        f"Erkannt als {resolved.name} {resolved.number or ''} — "
                        "Wert noch nicht berechnet"
                    )[:200]
                else:
                    # Der Grund wird MITGESCHRIEBEN, obwohl das ein Trockenlauf
                    # ist: Auflösen kostet nichts, und danach erklärt der Feed
                    # bei jeder Karte selbst, warum sie unbewertbar ist.
                    note_unresolvable(cand, trace)
                    print(f"    nicht auflösbar -> {trace[-1] if trace else 'unbewertbar'}")
                skipped += 1
            print(f"\n=== {valued} bewertet, {skipped} nicht bewertet ===\n")
            return

        # Vorauswahl ist gratis (nur TCGdex) und entscheidet, wofuer Geld fliesst.
        threshold = settings.single_card_lookup_threshold_eur
        candidates: list[Candidate] = []
        for cand in pool:
            if len(candidates) >= limit:
                break
            listing = cand.listing
            if listing is None:
                continue
            trace: list[str] = []
            if resolver.resolve(listing.title, listing.description, trace=trace) is None:
                # Auch hier den Grund festhalten — sonst bleibt der Kandidat im
                # Feed stumm "unbewertbar", obwohl wir ihn gerade geprüft haben.
                note_unresolvable(cand, trace)
                continue
            candidates.append(cand)

        if not candidates:
            print(
                f"\nKein auflösbarer Kandidat unter den letzten {len(pool)}.\n"
                "Mit --dry-run siehst du, woran es je Titel liegt.\n"
            )
            return

        print(f"\n=== {len(candidates)} auflösbare Kandidaten werden bewertet ===")
        print(f"(aus den letzten {len(pool)} unbewerteten; Schwelle {threshold} EUR)\n")

        for cand in candidates:
            listing = cand.listing
            price = f"{listing.price} {listing.currency}" if listing.price else "—"
            print(f"\n  #{cand.id}  {listing.title}")
            print(f"    Preis: {price}")

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
    parser.add_argument(
        "--verwerfen", action="store_true",
        help="Alle AUTOMATISCHEN Bewertungen löschen, damit sie neu gerechnet "
             "werden (Handarbeit bleibt unberührt)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.verwerfen:
        count = discard_auto_valuations()
        print(f"\n{count} automatische Bewertungen verworfen.")
        print("Sie werden beim nächsten Lauf neu gerechnet:")
        print("  python -m app.revalue --dry-run --limit 300   (kostenlos)")
        print("  python -m app.revalue --limit 20              (kostet Geld)\n")
        return
    run(limit=max(1, args.limit), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
