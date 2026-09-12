# PokeScanner

System zur Überwachung mehrerer Marktplätze auf unterbepreiste Pokémon-Karten,
Bewertung gegen echte Verkaufsdaten und Alarmierung.

> **V1 ist primär ein Messinstrument.** Die ersten Wochen protokolliert es Funde,
> um Fundfrequenz pro Kanal und Time-to-Contact zu messen. Kaufentscheidungen
> triffst du manuell.

## Status: Phase 1 (Fundament)

Geliefert:

- **Datenmodell + Migration** (`app/models/`, `migrations/`): Rohdaten
  (`listing`) / berechnete Werte (`reference_value`) / Urteile (`decision`)
  strikt getrennt (§5). Abgelehnte Kandidaten werden gespeichert. Jeder
  Referenzwert speichert `cascade_level` und `sample_size` (Pflicht). `purchase`
  trägt die §25a-UStG-Pflichtfelder als `NOT NULL`.
- **TCGdex-Client** (`app/clients/tcgdex.py`): Metadaten + Cardmarket-Preise,
  sauberer Umgang mit fehlendem `pricing` und Sprach-Fallback `de → en`.
- **SoldComps-Client** (`app/clients/soldcomps.py`): Paginierung über
  `hasNextPage` (nicht `totalItems`!), `hydrateBoa=true` Pflicht bei Sold,
  `X-Credit-Source: subscription-only` für Batch, optionale eBay-Cookies (Default
  aus), 429-Unterscheidung `quota_exceeded` vs. `Retry-After`, Rate-Throttle.
- **Referenzwert-Kaskade** (`app/pricing/`): Stufen 1–5 mit Stufen-/Sample-Logging
  und dem ehrlichen „unbewertbar" (Stufe 5).
- **Suchbegriff-Taxonomie** (`app/config_data/search_terms.yaml`): ~60
  Startbegriffe + Negativliste, zur Laufzeit editierbar.
- **Tests** für die Grenzfälle: leere Antwort, fehlendes `pricing`, 429,
  `hasNextPage`, jede Kaskadenstufe, Fenster-Filter, Adapter-Parsing.

**Noch nicht** (spätere Phasen, bewusst): FastAPI-Endpoints, Scheduler-Jobs,
Ingestion/Dedup, Discord, Vision, Frontend.

## Entscheidungen (in Config, tunbar)

| Parameter | Wert | Quelle |
|---|---|---|
| N (Mindeststichprobe / 90 Tage) | 5 | §6 |
| Zustandsfaktor (Stufe 2) | 0.6 | §6 |
| Sprachfaktor DE→EN (Stufe 3) | 0.8 | §6 |
| Zustands-Default | Played | §6 |
| Alarmschwelle Gewinn | 20 € | §7 |
| Kaufschwelle Versand / Abholung | 30 € / 80 € | §7 |
| Einzelkarten-Nachschlagschwelle | 15 € | §7 |

Stufe 3 nutzt englische Comps vom Markt `ebay.de` (kein FX in V1);
`reference_value.currency` bleibt im Schema für späteres ebay.com.

## Setup

```bash
cp .env.example .env         # SOLDCOMPS_API_KEY etc. eintragen
docker compose up -d db      # Postgres
docker compose run --rm app alembic upgrade head   # Migration
```

Lokal / Tests:

```bash
pip install -e ".[dev]"
pytest
```

## Offene Punkte für Phase-2-Review

- **§9 vs. §5:** Die Website soll jeden Comp einzeln anzeigen, das §5-Datenmodell
  hat aber keine Comp-Tabelle. Persistenz einzelner Comps ist für Phase 3
  (Website) nachzuziehen. In Phase 1 trägt das Kaskadenergebnis die Comps
  in-memory (`ReferenceResult.comps`).
- **Sprach-Bucketing der Sold-Comps** (§4.2 „erst ohne Filter, dann nachschärfen"
  vs. §6 „Sprache passend"): Die adaptive Policy ist bewusst NICHT im Orchestrator
  verdrahtet; der Aufrufer übergibt die Aspect-Filter. Festzulegen, wenn Phase 2
  den Live-Kanal anschließt.
- **Enum-CHECK-Constraints:** Enums sind als `VARCHAR(32)` gespeichert, Validierung
  auf ORM-Ebene (SQLAlchemy-2.0-Default). Bei Bedarf DB-seitige CHECKs nachrüsten.
