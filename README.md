# PokeScanner

System zur Überwachung mehrerer Marktplätze auf unterbepreiste Pokémon-Karten,
Bewertung gegen echte Verkaufsdaten und Alarmierung.

> **V1 ist primär ein Messinstrument.** Die ersten Wochen protokolliert es Funde,
> um Fundfrequenz pro Kanal und Time-to-Contact zu messen. Kaufentscheidungen
> triffst du manuell.

## Status: §9-Restansichten (Inventar, Kalibrierung, Kosten)

Die in Phase 3 zurückgestellten Website-Views (§9) sind ergänzt:

- **Inventar** (`GET /api/inventory`): offene Positionen (Kauf ohne Verkauf),
  Tage im Bestand, Exit-Regel-**Ampel** (§7: grün <45, gelb ≥45 → 25. Perzentil
  repricen, rot ≥90 → zum Gebot abstoßen).
- **Kalibrierung** (`GET /api/calibration`): Alarme pro Kanal, Trefferquote,
  „unbewertbar"-Rate, Ø Zeit vom Alarm bis Entscheidung, Ø Prognosefehler.
- **Kosten** (`GET /api/costs`): **echter** API-Verbrauch pro Quelle
  (`usage_event`-Tabelle, Migration 0005, pro Poll geschrieben) + geschätzte
  Kosten aus **konfigurierbaren** Stück-Kosten (`COST_*`, Default 0 → keine
  erfundenen Zahlen, R3). Kosten/Fund nur bei gesetzten Stück-Kosten.
- Frontend: drei neue dunkle Views + Navigation. 92 Tests.

## Status: Phase 5 (Weitere Kanäle)

Mehrkanal-Ingestion mit geteiltem Alarm-/Anreicherungs-Pfad und Cross-Channel-Dedup.

- **eBay Browse API** (`app/clients/ebay.py`, §4.3): OAuth2-Client-Credentials
  (Token gecached), Suche aktiver Listings, 403 (Tageslimit) / 429 unterschieden.
- **willhaben** (`app/ingest/sources.py`): über Apify, teilt den generischen
  Apify-Normalizer mit Kleinanzeigen.
- **Kanal-agnostische Pipeline** (`app/ingest/pipeline.py`, `sources.py`,
  `normalized.py`): iteriert `Source × aktive Begriffe`; Ingestion, Dedup,
  Alarm-Regel und Anreicherung sind geteilt. Sources werden per Config
  zu-/abgeschaltet (`*_ENABLED` + Credentials/Actor).
- **Cross-Channel-Dedup** (`app/ingest/dedup.py`, §5): aHash (Pillow) des ersten
  Bildes + Preis-Toleranz. Bildabruf nur für **alarmierende** Kandidaten
  (kostenbewusst). Cross-gepostete Anzeigen alarmieren nur einmal.
- **Tests**: eBay-Client (Token-Cache/Suche/403/429), Normalizer (eBay/willhaben),
  `build_sources`-Toggles, aHash/ImageHasher/Dedup-Lookup, und eine
  Pipeline-Integration (Alarm, Negativ-Ausschluss, seen-Dedup, Cross-Channel-Dedup).
  88 gesamt.

**Vinted** ist bewusst zurückgestellt (§11: DataDome/JA3 → teuerster Kanal, zuletzt).

## Status: Phase 4 (Anreicherung)

Vision-Triage + Textextraktion, **nach und parallel** zum Alarm — nie im
kritischen Pfad (§10). Alle KI-Ausgaben sind **Hinweise, nie Entscheidung/Preis**.

- **Textextraktion** (`app/enrich/text_extract.py`): deterministisch (kein LLM),
  scannt Titel+Beschreibung auf Zustandsmängel („Knick", „Kratzer", „bespielt",
  „Riss", …) → Flags.
- **Vision-Triage** (`app/enrich/vision.py`): Claude **Opus 5** (`claude-opus-5`),
  Bild-URLs → kurzer deutscher Triage-Hinweis. Prompt verbietet explizit Kauf-,
  Zustands-, Echtheitsurteil und Preis (§10). Client injizierbar (ohne Netz
  testbar).
- **Enrichment-Service** (`app/enrich/service.py`): persistiert Flags + Vision-Note
  (`enrichment`-Tabelle, Migration 0004) und **editiert das bestehende
  Discord-Embed** (R1) statt einer zweiten Nachricht.
- **Gating** (Pipeline): Textextraktion läuft immer; Vision nur bei Bildern und
  bis zum konfigurierbaren Cap `ENRICH_VISION_MAX_PER_POLL` (Default 20) pro Poll.
- **Sichtbar**: Anreicherung erscheint im Kandidaten-Detail (API + Frontend).
- **Tests**: Textextraktion, Vision (Fake-Client: Summary/Refusal/Gating/
  max-images), Enrichment-Service (SQLite + Fakes), API. 70 gesamt.

## Status: Phase 3 (Website)

Review, Journal und Decision-Erfassung (§9, §11). Dunkles, aufgeräumtes UI.

- **Backend-API** (`app/api/`, `app/main.py`): FastAPI mit
  - `GET /api/candidates` (Live Feed, neueste zuerst, `undecided_only`),
  - `GET /api/candidates/{id}` (Detail inkl. **einzeln aufgelisteter Comps**),
  - `PUT /api/candidates/{id}/decision` (Buy/Skip/Unclear + Fälschungsprüfung,
    `seconds_since_alert` wird berechnet),
  - `GET /api/journal` (abgeschlossene Deals, Prognose vs. Ergebnis).
- **Comp-Persistenz** (`reference_comp`, Migration 0003): löst den §9↔§5-Punkt —
  jeder Comp hinter einem Referenzwert wird gespeichert und ist im Detail
  nachprüfbar. Ask-Listings werden **nie** als Verkäufe gezählt.
- **Frontend** (`frontend/`, React + Vite + Tailwind, dunkles Theme): Live Feed
  (Bild, Preis, Gewinn/„unbewertbar", Kaskadenstufe), Kandidaten-Detail (alle
  Bilder groß, volle Beschreibung, Comps-Tabelle, Buy/Skip/Unclear mit
  Pflicht-Fälschungsprüfung und Grund), Journal.
- **Portable Model-Typen**: `JSONB`/`ARRAY` mit Variant → auf SQLite `JSON`, damit
  die API ohne Postgres integrationsgetestet werden kann (Migrationen bleiben
  Postgres-nativ). 58 Tests, inkl. API-Integrationstests.

**Noch nicht** (§9-Views außerhalb des Phase-3-Umfangs, bewusst): Inventar
(Bestandstage/Exit-Ampel), Kalibrierung (Trefferquote, Time-to-Decision,
Prognosefehler), Kosten (API-Verbrauch je Quelle). Diese folgen nach Review.

## Status: Phase 2 (Ein Kanal — Kleinanzeigen)

Ab hier **läuft und misst** das System (§11). Geliefert in Phase 2:

- **Apify-Client** (`app/clients/apify.py`): Actor synchron ausführen
  (`run-sync-get-dataset-items`), `maxItems`-Cap gegen Kosten, 402 (Usage-Limit)
  und 429 sauber unterschieden.
- **Ingestion + Normalisierung** (`app/ingest/kleinanzeigen.py`): defensives
  Feld-Mapping (Actor-agnostisch), deutscher Preis-Parser (`VB`/leer → kein
  Preis, „Zu verschenken" → 0, `1.234 €` → 1234), Verkäufertyp-Mapping.
- **Dedup** (`app/ingest/repo.py`): innerhalb des Kanals über
  `(channel, external_id)` — wiedergesehene Listings aktualisieren `last_seen_at`
  und lösen **keinen** erneuten Alarm aus.
- **Alarm-Regel** (`app/ingest/alarm.py`): billiges Gate — Negativliste + (default
  aus) Preis-Guards. Jeder Fund ist in Phase 2 „unbewertbar" (keine Karten-ID)
  und feuert trotzdem (R4). Preislose Listings feuern (Default).
- **Discord-Alarm** (`app/alerts/`): Embed mit Bild, Titel, Preis (bzw. „Preis
  unbekannt"), Gewinn („unbewertbar"), Kaskade, Kanal, Ort, Suchbegriff und
  **vorformulierter Kontaktnachricht zum Kopieren**. Message-ID wird gespeichert,
  damit spätere Anreicherung dasselbe Embed **editiert** (R1).
- **Pipeline + Scheduler** (`app/ingest/pipeline.py`, `app/scheduler.py`):
  gestaffelter Poll — tags alle 15 min (08–23 Uhr), nachts alle 60 min, alles in
  Config. Jeder Kandidat speichert den auslösenden Suchbegriff
  (`matched_search_term`) → datenbasierte Rotation der aktiven Query-Teilmenge.
- **Tests** für Preis-Parser, Normalisierung, Alarm-Regel, Apify-Client,
  Discord-Embed und Scheduler-Trigger.

Alarm-Pfad läuft als Worker (kein Web-Server): `docker compose up` migriert und
startet den Scheduler.

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

**Noch nicht** (spätere Phasen, bewusst): Website/Decision-Erfassung (Phase 3),
Vision-/Text-Anreicherung (Phase 4), weitere Kanäle — eBay Browse, willhaben,
Vinted (Phase 5), Cross-Channel-Dedup via Bildhash.

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
| Preisobergrenze Alarm | keine (aus) | Phase 2 |
| Listings ohne Preis feuern | ja | Phase 2 |
| Aktive Query-Teilmenge | ~8 (`search_terms.yaml`) | §4.4 |
| Poll tags / nachts | 15 min (08–23) / 60 min | §11 |

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

### Frontend (React + Tailwind)

```bash
cd frontend
npm install
npm run dev      # Vite dev-Server auf :5173, proxyt /api -> :8000
# oder für Produktion:
npm run build    # statisches Bundle in frontend/dist/
```

Backend-API lokal starten:

```bash
uvicorn app.main:app --reload   # :8000
```

Mit Docker läuft alles zusammen (`db` + `migrate` + `api` + `worker`) via
`docker compose up`; das Frontend wird separat gebaut/ausgeliefert.

## Offene Punkte

- **§9 vs. §5:** ✅ gelöst in Phase 3 — `reference_comp`-Tabelle (Migration 0003)
  speichert jeden Comp einzeln; das Kandidaten-Detail listet sie auf.
- **Cross-Channel-Dedup:** ✅ aHash + Preis-Toleranz, nur für alarmierende
  Kandidaten (bounded). Optionale **Hamming-Toleranz** (`DEDUP_HAMMING_THRESHOLD`,
  Default 0 = exakt) für re-enkodierte Bilder.
- **CORS:** ✅ konfigurierbar (`CORS_ALLOW_ORIGINS`); `*` nur als Dev-Default.
- **Sprach-Bucketing der Sold-Comps** (§4.2 „erst ohne Filter, dann nachschärfen"
  vs. §6 „Sprache passend"): Die adaptive Policy ist bewusst NICHT im Orchestrator
  verdrahtet; der Aufrufer übergibt die Aspect-Filter. Festzulegen, wenn Phase 2
  den Live-Kanal anschließt.
- **Enum-CHECK-Constraints:** Enums sind als `VARCHAR(32)` gespeichert, Validierung
  auf ORM-Ebene (SQLAlchemy-2.0-Default). Bei Bedarf DB-seitige CHECKs nachrüsten.
