# PokeScanner — Einrichtung & Start

Schritt-für-Schritt, damit die echte Scan-Maschine läuft. Du brauchst einen
Rechner (oder kleinen Server/VPS) mit **Docker** — das ist der einfachste Weg.

## 1. Code holen

```bash
git clone -b claude/adoring-feynman-awnoqk https://github.com/justtheboisgang/PokeScanner.git
cd PokeScanner
```

## 2. Zugänge in die `.env` eintragen

```bash
cp .env.example .env
```

Dann `.env` in einem Editor öffnen und diese Werte setzen (Rest kann Standard bleiben):

```env
# Discord (wohin die Alarme gehen)
DISCORD_WEBHOOK_URL=DEIN_DISCORD_WEBHOOK

# Apify (liest Kleinanzeigen aus)
APIFY_TOKEN=DEIN_APIFY_TOKEN
APIFY_KLEINANZEIGEN_ACTOR=beatanalytics~kleinanzeigen-scraper
KLEINANZEIGEN_ENABLED=true

# Anthropic (Vision-Triage; du hattest Opus gewählt)
ANTHROPIC_API_KEY=DEIN_NEUER_ANTHROPIC_KEY
ENRICH_VISION_ENABLED=true
ENRICH_VISION_MODEL=claude-opus-5
ENRICH_VISION_MAX_PER_POLL=20
```

> **Wichtig:** Die `.env` wird **nie** ins Git hochgeladen (sie ist ausgeschlossen).
> Trage Geheimnisse nur hier ein, nirgends sonst.

**Den Apify-Token findest du** auf apify.com → Konto → *Settings → Integrations → API token*.

## 3. Erst einmal testen (ein einzelner Lauf)

Bevor der Dauerbetrieb startet, ein Probelauf — der fragt einmal ab, schreibt in
die Datenbank und schickt bei Treffern Discord-Alarme:

```bash
docker compose up -d db                      # Datenbank starten
docker compose run --rm migrate              # Tabellen anlegen
docker compose run --rm worker python -m app.pollonce
```

Du siehst am Ende eine Zusammenfassung (wie viele Listings gesehen, wie viele
Alarme gesendet). Kommen **0 Listings**, liefert der Actor vermutlich ein anderes
Eingabeformat — dann in `.env` einmal setzen und erneut testen:

```env
APIFY_KLEINANZEIGEN_INPUT={"keywords":"{{query}}","maxItems":40}
```

(Schick mir sonst die Ausgabe des Probelaufs, dann passe ich die Feld-Zuordnung an.)

## 4. Dauerbetrieb starten

```bash
docker compose up -d
```

Das startet drei Dienste:
- **db** — die Datenbank
- **worker** — der Scanner (pollt tagsüber alle 15 Min, nachts alle 60 Min)
- **api** — das Backend für die Website (Port 8000)

Ab jetzt tickt es von selbst und schickt Alarme nach Discord.

Logs ansehen: `docker compose logs -f worker`
Stoppen: `docker compose down`

## 5. Die Website (Review-Oberfläche) öffnen

Das Backend läuft schon (Port 8000). Die Oberfläche startest du separat:

```bash
cd frontend
npm install
npm run dev
```

Dann im Browser **http://localhost:5173** öffnen — dort siehst du Live Feed,
Kandidaten-Detail (mit Buy/Skip/Unclear), Inventar, Journal, Kalibrierung, Kosten.

## Kosten im Blick behalten

- **Apify** kostet pro Ergebnis + Proxy-Bandbreite. `APIFY_MAX_ITEMS_PER_QUERY`
  begrenzt es. Setz dir in Apify ein Usage-Limit.
- **Vision (Opus 5)** ist das teuerste Stück. `ENRICH_VISION_MAX_PER_POLL=20`
  deckelt die Zahl der Bild-Analysen pro Lauf. Zu teuer? In `.env`
  `ENRICH_VISION_MODEL=claude-haiku-4-5` setzen (viel günstiger) oder
  `ENRICH_VISION_ENABLED=false`.
- Der Reiter **Kosten** in der Website zeigt den echten Verbrauch pro Quelle.

## Wichtig (deine Regeln aus dem Konzept)

- **Getrennte Konten (R5):** Für Monitoring/Scraping eigene Konten nutzen, nicht
  deinen echten Kauf-/Verkaufsaccount.
- **V1 ist ein Messinstrument:** Kaufentscheidungen triffst *du* — das System
  meldet und sortiert vor. C2C-Funde sind zunächst als „unbewertbar" markiert.
- Die API hat **keine Anmeldung** — nicht offen ins Internet stellen, sondern
  lokal/hinter VPN oder Firewall betreiben (siehe README, Abschnitt Sicherheit).
