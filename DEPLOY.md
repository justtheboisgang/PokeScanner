# PokeScanner auf einem VPS betreiben (Block 4)

Ziel: der Scanner läuft 24/7 ohne deinen PC, alarmiert auf Discord und die
Website ist von außen erreichbar — aber nicht für jeden.

V1 bleibt ein **Messinstrument**: die Maschine liefert Abdeckung, Tempo,
Alarme und Buchhaltung. Karten erkennen und bewerten tust du.

---

## 1. Was du brauchst

- Ein kleiner VPS (2 GB RAM reichen), Ubuntu 22.04/24.04, mit root/sudo
- Eine Domain oder Subdomain, die auf die VPS-IP zeigt (für HTTPS)
- Deine Secrets: `APIFY_TOKEN`, `DISCORD_WEBHOOK_URL`, optional `SOLDCOMPS_API_KEY`

## 2. Docker installieren

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # danach einmal neu einloggen
```

## 3. Projekt holen und konfigurieren

```bash
git clone <dein-repo> pokescanner
cd pokescanner
cp .env.example .env
nano .env
```

In der `.env` **mindestens** setzen:

```ini
DATABASE_URL=postgresql+psycopg://poke:EIN_STARKES_PASSWORT@db:5432/pokescanner
APIFY_TOKEN=apify_api_...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Website-Schutz (Block 4) — ohne das ist die Seite offen im Netz!
WEB_USERNAME=poke
WEB_PASSWORD=EIN_LANGES_ZUFALLSPASSWORT

# Nur deine Domain darf die API aufrufen
CORS_ALLOW_ORIGINS=https://poke.deine-domain.de
```

> **Wichtig:** `db:5432` (nicht `localhost`) — innerhalb von Compose heißt der
> Datenbank-Container `db`. Und das Passwort in `DATABASE_URL` muss zu dem in
> `docker-compose.yml` passen (siehe Schritt 4).

Ein starkes Passwort erzeugen:

```bash
openssl rand -base64 24
```

## 4. Datenbank-Passwort setzen

In `docker-compose.yml` das Default-Passwort `poke` ersetzen:

```yaml
  db:
    environment:
      POSTGRES_PASSWORD: EIN_STARKES_PASSWORT
```

Und den Port **nicht** nach außen veröffentlichen. Die Zeilen

```yaml
    ports:
      - "5432:5432"
```

beim `db`-Service löschen — nur die App muss die Datenbank erreichen, nicht das
Internet.

## 5. Starten

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f worker
```

Erwartete Log-Zeile beim Start des Workers:

```
scheduler starting (tz=Europe/Berlin, day 08:00-23:00 every 15m, night every 60m, health check after 3h silence)
```

Migrationen laufen automatisch im `migrate`-Container, bevor API und Worker
starten.

## 6. Frontend bauen und ausliefern

```bash
cd frontend
npm ci
npm run build          # Ergebnis: frontend/dist
```

`frontend/dist` mit einem Webserver ausliefern. Beispiel-nginx, das die Seite
ausliefert und `/api` an die FastAPI weiterreicht:

```nginx
server {
    server_name poke.deine-domain.de;

    root /opt/pokescanner/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;   # SPA-Routing
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 7. HTTPS

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d poke.deine-domain.de
```

HTTP Basic sendet das Passwort bei jedem Request — **nur hinter HTTPS
betreiben**, sonst geht es im Klartext über die Leitung.

### Wie der Login aussieht

Du rufst die Seite auf, der erste API-Aufruf kommt mit `401` zurück, und der
Browser fragt dich in seinem eigenen Dialog nach Benutzername und Passwort
(`WEB_USERNAME` / `WEB_PASSWORD`). Danach schickt er sie automatisch mit —
kein Logout-Knopf, Abmelden heißt Browserfenster schließen.

Wer die **ganze** Seite (nicht nur die API) hinter das Passwort stellen will,
ergänzt in nginx im `location /`-Block:

```nginx
    auth_basic "PokeScanner";
    auth_basic_user_file /etc/nginx/.htpasswd;
```

mit `sudo htpasswd -c /etc/nginx/.htpasswd poke`.

## 8. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Port 8000 (FastAPI) und 5432 (Postgres) bleiben dicht — nginx spricht über
localhost mit der API.

---

## Betrieb

### Health-Check

Der Worker schreibt nach **jedem** abgeschlossenen Poll einen Heartbeat, auch
wenn nichts gefunden wurde. Kommt länger als `HEALTH_MAX_SILENCE_HOURS`
(Default 3 h) kein Heartbeat, warnt der Scanner auf Discord:

> ⚠️ PokeScanner: seit 4.2 h kein erfolgreicher Scan (Grenze 3 h). Läuft der Worker noch?

Die Warnung wiederholt sich frühestens nach `HEALTH_WARN_COOLDOWN_HOURS`, damit
ein dauerhaft toter Worker nicht im Minutentakt spammt.

Selbst prüfen:

```bash
curl -s localhost:8000/api/health        # ohne Passwort erreichbar
docker compose logs --tail=50 worker
```

### Poll-Takt

| Zeitfenster | Takt |
|---|---|
| 08:00–23:00 | alle 15 min |
| 23:00–08:00 | alle 60 min |

Über `POLL_DAY_INTERVAL_MINUTES`, `POLL_NIGHT_INTERVAL_MINUTES`,
`POLL_DAY_START_HOUR`, `POLL_DAY_END_HOUR` anpassbar.

### Kosten im Blick

Tagesbudgets je Provider greifen hart: ist das Budget erschöpft, wird der
Provider für den Rest des Tages deaktiviert und du bekommst **eine** Warnung auf
Discord. Die Kosten-Ansicht der Website zeigt Ausgaben je Provider und die
Kosten pro Fund.

### Backup

Die Buchhaltung (Käufe mit §25a-Erwerbsdaten, Verkäufe) steckt in Postgres:

```bash
docker compose exec -T db pg_dump -U poke pokescanner | gzip > backup-$(date +%F).sql.gz
```

Als tägliches Cron-Backup:

```bash
crontab -e
# 0 4 * * * cd /opt/pokescanner && docker compose exec -T db pg_dump -U poke pokescanner | gzip > /var/backups/poke-$(date +\%F).sql.gz
```

### Updates einspielen

```bash
git pull
docker compose up -d --build       # migrate laeuft automatisch mit
cd frontend && npm ci && npm run build
```

### Logs

```bash
docker compose logs -f worker      # Scans, Alarme, Budget-Warnungen
docker compose logs -f api         # Website-Zugriffe
```

---

## Sicherheits-Checkliste vor dem Scharfschalten

- [ ] `WEB_PASSWORD` gesetzt (sonst ist die Seite offen)
- [ ] HTTPS aktiv (Basic Auth sonst im Klartext)
- [ ] `CORS_ALLOW_ORIGINS` auf deine Domain gesetzt, nicht `*`
- [ ] Postgres-Port nicht veröffentlicht, DB-Passwort geändert
- [ ] `.env` ist nicht im Git (steht in `.gitignore`)
- [ ] Backup-Cron läuft
