"""Run a single poll now and print the stats. Handy for setup/testing.

    python -m app.pollonce

Uses the same enabled sources, alarm rule, Discord alert and enrichment as the
scheduler — just once instead of on a timer.
"""

from __future__ import annotations

import logging

from app.ingest.pipeline import build_pipeline


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # Don't log request URLs (they can carry tokens/query params).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    stats = build_pipeline().poll()
    print("\n=== Poll-Ergebnis ===")
    print(f"Quellen-Abfragen : {stats.queries}")
    print(f"Listings gesehen : {stats.items_seen}")
    print(f"Neue Listings    : {stats.new_listings}")
    print(f"Alarme gesendet  : {stats.alerts_sent}")
    print(f"Ausgeschlossen   : {stats.skipped_excluded}")
    print(f"Schon bekannt    : {stats.skipped_seen}")
    print(f"Dubletten        : {stats.deduped}")
    print(f"Vision-Calls     : {stats.vision_calls}")
    print(f"Fehler           : {stats.errors}")
    if stats.per_source_queries:
        print(f"Pro Quelle       : {stats.per_source_queries}")


if __name__ == "__main__":
    main()
