"""Konfigurations-Check: was ist gesetzt, was fehlt, was läuft daraus (Betrieb).

Beantwortet die Frage "warum passiert nichts?" ohne Geheimnisse zu verraten:
Werte werden maskiert ausgegeben, nie im Klartext. Aufruf:

    docker compose run --rm worker python -m app.checkconfig
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.config_data import load_search_terms
from app.scheduler import night_hours

OK = "OK  "
MISS = "FEHLT"
OFF = "AUS "


def mask(value: str) -> str:
    """Show only that a secret is set, plus its length — never the value."""
    if not value:
        return "(leer)"
    return f"{value[:3]}…{value[-2:]} ({len(value)} Zeichen)"


def line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label:28} {detail}")


def report(settings: Settings | None = None) -> bool:
    """Print the config report. Returns True if the scanner can do useful work."""
    s = settings or get_settings()
    terms = load_search_terms()

    print("\n=== PokeScanner Konfigurations-Check ===\n")

    print("Zugangsdaten (.env):")
    line(OK if s.apify_token else MISS, "APIFY_TOKEN", mask(s.apify_token))
    line(
        OK if s.discord_webhook_url else MISS,
        "DISCORD_WEBHOOK_URL",
        "gesetzt" if s.discord_webhook_url else "(leer) — keine Alarme!",
    )
    line(
        OK if s.soldcomps_api_key else MISS,
        "SOLDCOMPS_API_KEY",
        mask(s.soldcomps_api_key) if s.soldcomps_api_key
        else "(leer) — Karten werden erfasst, aber NICHT bewertet",
    )
    line(
        OK if s.ebay_client_id else OFF,
        "EBAY_CLIENT_ID",
        mask(s.ebay_client_id),
    )
    line(
        OK if s.ebay_client_secret else OFF,
        "EBAY_CLIENT_SECRET",
        mask(s.ebay_client_secret),
    )
    line(
        OK if s.pokewallet_api_key else OFF,
        "POKEWALLET_API_KEY",
        mask(s.pokewallet_api_key) if s.pokewallet_api_key
        else "(leer) — keine Marktpreise, keine Markt-vs-Verkauf-Analyse",
    )

    print("\nQuellen, die daraus wirklich laufen:")
    # Eine Quelle zählt nur als laufend, wenn auch ihre Zugangsdaten da sind —
    # ein grüner Haken ohne Token wäre eine Lüge.
    ka = (
        s.kleinanzeigen_enabled
        and bool(s.apify_kleinanzeigen_actor)
        and bool(s.apify_token)
    )
    eb = s.ebay_browse_enabled and bool(s.ebay_client_id) and bool(s.ebay_client_secret)
    wh = (
        s.willhaben_enabled
        and bool(s.apify_willhaben_actor)
        and bool(s.apify_token)
    )
    line(
        OK if ka else OFF,
        "Kleinanzeigen",
        "aktiv (Apify)"
        if ka
        else (
            "KLEINANZEIGEN_ENABLED=true, aber APIFY_TOKEN fehlt"
            if s.kleinanzeigen_enabled and not s.apify_token
            else "aus"
        ),
    )
    line(
        OK if eb else OFF,
        "eBay Browse",
        "aktiv (gratis)"
        if eb
        else (
            "EBAY_BROWSE_ENABLED=true, aber Client-ID/Secret fehlt"
            if s.ebay_browse_enabled
            else "aus (EBAY_BROWSE_ENABLED=false)"
        ),
    )
    line(OK if wh else OFF, "willhaben", "aktiv" if wh else "aus")
    active_sources = sum((ka, eb, wh))

    print("\nBewertung:")
    if s.soldcomps_api_key:
        line(OK, "Automatisch (Einzelkarten)",
             "an" if s.enrich_auto_value_enabled else "aus (ENRICH_AUTO_VALUE_ENABLED)")
        line(OK, "Manuell (Konvolute)", "Knopf 'Bewerten' liefert echte Werte")
    else:
        line(MISS, "Automatisch (Einzelkarten)", "braucht SOLDCOMPS_API_KEY")
        line(MISS, "Manuell (Konvolute)", "Karten werden nur erfasst")
    # Marktpreise haengen nicht an SoldComps: sie tragen Stufe 4 auch dann,
    # wenn die Verkaufsseite gerade klemmt.
    if s.pokewallet_api_key:
        line(OK, "Marktpreise (Stufe 4)", "PokeWallet — auch ohne SoldComps nutzbar")
    else:
        line(OFF, "Marktpreise (Stufe 4)", "nur TCGdex (lückenhaft bei Vintage)")

    print("\nScan-Takt und Volumen:")
    polls = (s.poll_day_end_hour - s.poll_day_start_hour) * (
        60 // s.poll_day_interval_minutes
    ) + len(night_hours(s.poll_day_start_hour, s.poll_day_end_hour))
    n = len(terms.active)
    line(OK, "Suchbegriffe (aktiv)", str(n))
    line(
        OK,
        "Polls pro Tag",
        f"{polls} ({s.poll_day_start_hour:02d}-{s.poll_day_end_hour:02d} Uhr alle "
        f"{s.poll_day_interval_minutes} min, nachts alle {s.poll_night_interval_minutes} min)",
    )
    if ka:
        line(OK, "Apify-Runs pro Tag", f"{polls * n}  (Budget {s.budget_apify_daily_eur} EUR/Tag)")
    if eb:
        line(OK, "eBay-Calls pro Tag", f"{polls * n}  (gratis, Limit ca. 5000)")
    # Die Schwelle stammt oft aus der .env und ueberschreibt die Vorgabe. Sie
    # hier zu zeigen erspart die Sucherei, wenn "alles unbewertbar" gemeldet wird.
    thr = s.single_card_lookup_threshold_eur
    line(
        OK if thr <= 5 else OFF,
        "Nachschlagschwelle",
        f"{thr} EUR — eBay-Angebote darunter werden nicht bewertet"
        + ("" if thr <= 5 else "  <- hoch, blockiert evtl. echte Funde"),
    )

    print("\nWebsite:")
    line(
        OK if s.web_password else OFF,
        "Passwortschutz",
        "an" if s.web_password else "AUS — nur lokal vertretbar",
    )

    print()
    ok = active_sources > 0 and bool(s.discord_webhook_url)
    if not ok:
        print("!! Der Scanner kann so nichts Nützliches tun.")
        if active_sources == 0:
            print("   Keine Quelle aktiv — prüfe APIFY_TOKEN / EBAY_*.")
        if not s.discord_webhook_url:
            print("   Kein Discord-Webhook — es käme kein Alarm an.")
    elif not s.soldcomps_api_key:
        print("Scanner läuft und alarmiert. Bewerten kann er noch nicht:")
        print("   SOLDCOMPS_API_KEY in die Datei .env eintragen (NICHT .env.example!),")
        print("   danach: docker compose up -d")
    else:
        print("Alles gesetzt. Scanner alarmiert und bewertet.")
    print()
    return ok


if __name__ == "__main__":
    report()
