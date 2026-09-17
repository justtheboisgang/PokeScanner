"""Warum wurde dieser Titel nicht automatisch bewertet? (Diagnose)

Zeigt Tor für Tor, woran die automatische Auflösung scheitert — mit den echten
TCGdex-Antworten, nicht mit Vermutungen.

    docker compose run --rm worker python -m app.explain "Schiggy 63/102 Base Set"

Ohne Argument werden die zuletzt gespeicherten unbewerteten Kandidaten geprüft.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.clients.tcgdex import TCGdexClient
from app.config import get_settings
from app.db import session_scope
from app.models.candidate import Candidate
from app.models.enums import Language
from app.pricing.resolver import SingleCardTitleResolver


def _resolver() -> SingleCardTitleResolver:
    settings = get_settings()
    lang = Language.DE if settings.tcgdex_primary_lang == "de" else Language.EN
    return SingleCardTitleResolver(TCGdexClient(), lang=lang)


def explain(title: str, resolver: SingleCardTitleResolver | None = None) -> bool:
    """Print the gate-by-gate trace. Returns True if the title resolved."""
    resolver = resolver or _resolver()
    trace: list[str] = []
    try:
        resolved = resolver.resolve(title, None, trace)
    except Exception as exc:  # noqa: BLE001 — Diagnose soll nie abbrechen
        print(f"\n  {title}")
        print(f"    FEHLER beim Auflösen: {exc!r}")
        return False

    print(f"\n  {title}")
    for step in trace:
        print(f"    {step}")
    if resolved is None:
        print("    => unbewertbar (du musst die Karte selbst eintragen)")
        return False
    print(
        f"    => BEWERTBAR: {resolved.name} | Nr. {resolved.number} | "
        f"{resolved.language.value} | {resolved.printing.value}"
    )
    return True


def explain_recent(limit: int = 15) -> None:
    """Check the newest candidates that carry no reference value yet."""
    with session_scope() as session:
        rows = session.scalars(
            select(Candidate)
            .where(Candidate.reference_value_id.is_(None))
            .order_by(Candidate.id.desc())
            .limit(limit)
        ).all()
        titles = [c.listing.title for c in rows if c.listing is not None]

    if not titles:
        print("Keine unbewerteten Kandidaten in der Datenbank.")
        return

    resolver = _resolver()
    ok = sum(explain(t, resolver) for t in titles)
    print(f"\n=== {ok} von {len(titles)} wären automatisch bewertbar ===\n")


def main(argv: list[str] | None = None) -> None:
    args = (argv if argv is not None else sys.argv[1:])
    if args:
        resolver = _resolver()
        for title in args:
            explain(title, resolver)
        print()
    else:
        explain_recent()


if __name__ == "__main__":
    main()
