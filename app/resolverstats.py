"""Erkennungsquote messen (Diagnose, kostenlos).

Die Frage "wie viele Karten erkennt das System eigentlich?" war bisher nicht
beantwortbar — es gab nur den Eindruck aus dem Feed. Dieser Befehl laesst den
Resolver ueber die gespeicherten Inserate laufen und rechnet die Quote aus,
getrennt nach dem, was die Automatik ueberhaupt erkennen SOLL:

    Konvolute  gehoeren dem Betreiber (V1 ist ein Messinstrument), nicht der
               Automatik. Sie duerfen die Quote nicht verwaessern.
    Neudrucke  sind Einzelkarten, werden aber bewusst abgelehnt: ihre Nummer
               gehoert dem Original, ein automatischer Wert waere erfunden.
    Einzelkarten sind der Massstab. Auf sie bezieht sich die Prozentzahl.

    docker compose run --rm worker python -m app.resolverstats
    docker compose run --rm worker python -m app.resolverstats --limit 300
    docker compose run --rm worker python -m app.resolverstats --zeige-titel

Es kostet nichts: nur TCGdex wird gefragt, und das ist gratis. Es werden aber
mehrere Anfragen je Titel gestellt, deshalb ist das Limit bewusst klein.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from sqlalchemy import select

from app.clients.tcgdex import TCGdexClient
from app.config import get_settings
from app.db import session_scope
from app.models.enums import Language
from app.models.listing import Listing
from app.pricing.resolver import (
    SingleCardTitleResolver,
    extract_card_number,
    looks_like_bundle,
    looks_like_reprint,
    looks_like_sealed_product,
)

logger = logging.getLogger(__name__)

# Die Spur des Resolvers ist Freitext. Fuer die Uebersicht wird sie auf wenige
# Koerbe abgebildet, sonst zaehlt man 300 verschiedene Einzelgruende.
_BUCKETS: tuple[tuple[str, str], ...] = (
    ("Tor 1b", "keine Kartennummer im Titel"),
    ("mehrdeutig", "Nummer passt auf mehrere Karten"),
    ("keine gefunden", "Karte bei TCGdex nicht gefunden"),
    ("Namenswort", "kein brauchbarer Kartenname im Titel"),
    ("ohne Namen", "TCGdex-Treffer ohne Namen"),
)


def _bucket(trace: list[str]) -> str:
    last = trace[-1] if trace else ""
    for needle, label in _BUCKETS:
        if needle.lower() in last.lower():
            return label
    return last or "unbekannt"


def _pct(part: int, whole: int) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "—"


def run(limit: int = 150, show_titles: bool = False,
        show_hits: bool = False) -> int:
    settings = get_settings()
    lang = Language.DE if settings.tcgdex_primary_lang == "de" else Language.EN
    resolver = SingleCardTitleResolver(TCGdexClient(), lang=lang)

    bundles = reprints = products = 0
    singles: list[tuple[str, bool, str]] = []  # (Titel, erkannt, Grund)
    hits: list[tuple[str, str]] = []           # (Titel, worauf aufgeloest)

    with session_scope() as session:
        stmt = select(Listing).order_by(Listing.id.desc())
        if limit > 0:
            stmt = stmt.limit(limit)
        listings = session.scalars(stmt).all()
        total = len(listings)
        if not total:
            print("Keine Inserate in der Datenbank.")
            return 0
        # Der Id-Bereich gehoert in die Ausgabe: "die letzten 300" ist ein
        # wanderndes Ziel. Zwischen zwei Laeufen kommen hunderte neue Inserate
        # dazu, und dann vergleicht man zwei voellig verschiedene Stichproben
        # und haelt den Unterschied faelschlich fuer eine Verbesserung oder
        # eine Verschlechterung. Mit --alle ist die Zahl ueber die Zeit
        # vergleichbar.
        lo = min(listing.id for listing in listings)
        hi = max(listing.id for listing in listings)
        scope = "alle" if limit <= 0 else f"die letzten {total}"
        print(f"\n=== Erkennungsquote ueber {scope} Inserate (Id {lo}-{hi}) ===")
        print("(kostenlos — es wird nur TCGdex gefragt)\n")

        for listing in listings:
            title = listing.title or ""
            if looks_like_bundle(title):
                bundles += 1
                continue
            if looks_like_reprint(title):
                reprints += 1
                continue
            # Displays, Booster, Muenzen, sogar Game-Boy-Spiele laufen ueber
            # dieselben Suchbegriffe mit. Sie als "Karte nicht erkannt" zu
            # zaehlen waere falsch — sie sind gar keine Karte. Nur wenn auch
            # keine Kartennummer dasteht: "Glurak 4/102 aus Booster" bleibt
            # eine Karte.
            if extract_card_number(title) is None and looks_like_sealed_product(title):
                products += 1
                continue
            trace: list[str] = []
            try:
                resolved = resolver.resolve(title, listing.description, trace=trace)
            except Exception as exc:  # noqa: BLE001 — Diagnose bricht nie ab
                singles.append((title, False, f"Fehler: {exc!r}"))
                continue
            singles.append((title, resolved is not None, _bucket(trace)))
            if resolved is not None:
                hits.append(
                    (title, f"{resolved.name} {resolved.number or ''} "
                            f"[{resolved.tcgdex_id}]")
                )

    recognized = sum(1 for _, ok, _ in singles if ok)
    measured = len(singles)

    print(f"Konvolute / Sammlungen : {bundles:>4}  ({_pct(bundles, total)})"
          "   — Handarbeit, nicht Automatik")
    print(f"Neudrucke / Jubilaeen  : {reprints:>4}  ({_pct(reprints, total)})"
          "   — bewusst abgelehnt")
    print(f"Zubehoer / versiegelt  : {products:>4}  ({_pct(products, total)})"
          "   — gar keine Einzelkarte")
    print(f"Einzelkarten           : {measured:>4}  ({_pct(measured, total)})")
    print(f"  davon ERKANNT        : {recognized:>4}  ({_pct(recognized, measured)})"
          "   <- die Quote, um die es geht")
    print(f"  davon nicht erkannt  : {measured - recognized:>4}")

    misses = Counter(reason for _, ok, reason in singles if not ok)
    if misses:
        print("\nWoran es bei den nicht erkannten lag:")
        for reason, count in misses.most_common():
            print(f"  {count:>4}  {reason}")

    if show_hits:
        # Die Quote sagt, WIE VIELE aufgeloest wurden — nicht, ob richtig.
        # Ein falsch aufgeloester Titel erfindet einen Wert, und das faellt
        # nur auf, wenn jemand draufschaut. Deshalb diese Liste.
        print("\nErkannt als — bitte stichprobenartig pruefen:")
        for title, target in hits:
            print(f"  {title[:78]}")
            print(f"      -> {target}")

    if show_titles:
        misses_list = [(t, r) for t, ok, r in singles if not ok]
        shown = misses_list[:40]
        print(f"\nNicht erkannte Titel ({len(shown)} von {len(misses_list)}):")
        for title, reason in shown:
            print(f"  - {title[:90]}")
            print(f"      {reason}")

    print()
    return recognized


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s [%(name)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Erkennungsquote des Resolvers messen")
    parser.add_argument("--limit", type=int, default=150,
                        help="Wie viele Inserate pruefen (Default 150)")
    parser.add_argument("--alle", action="store_true",
                        help="ALLE gespeicherten Inserate pruefen — die einzige "
                             "ueber die Zeit vergleichbare Zahl")
    parser.add_argument("--zeige-titel", action="store_true", dest="show_titles",
                        help="Jeden nicht erkannten Titel mit Grund auflisten")
    parser.add_argument("--zeige-treffer", action="store_true", dest="show_hits",
                        help="Zeigen, ALS WAS erkannt wurde (Gegenprobe zur Quote)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    run(limit=0 if args.alle else max(1, args.limit),
        show_titles=args.show_titles, show_hits=args.show_hits)


if __name__ == "__main__":
    main()
