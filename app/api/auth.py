"""Passwortschutz für die Website (Block 4).

Die Instanz läuft auf einem VPS und hängt am offenen Netz; ohne Schutz kann
jeder die Kandidaten, Käufe und Erwerbsdaten (§25a) lesen. HTTP Basic reicht
für eine Ein-Personen-Instanz hinter HTTPS und kostet keine Session-Logik.

Ist WEB_PASSWORD leer, ist der Schutz aus (lokale Entwicklung). /api/health
bleibt immer offen, damit Monitoring/Compose den Dienst prüfen kann.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_UNPROTECTED = ("/api/health",)
_CHALLENGE = {"WWW-Authenticate": 'Basic realm="PokeScanner"'}


def _credentials_ok(header: str | None, username: str, password: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    user, _, pwd = raw.partition(":")
    # Constant-time on both halves so neither can be probed by timing.
    user_ok = secrets.compare_digest(user, username)
    pwd_ok = secrets.compare_digest(pwd, password)
    return user_ok and pwd_ok


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, username: str, password: str) -> None:
        super().__init__(app)
        self.username = username
        self.password = password

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        # CORS preflight carries no credentials by design.
        if request.method == "OPTIONS" or path in _UNPROTECTED:
            return await call_next(request)
        if not _credentials_ok(
            request.headers.get("authorization"), self.username, self.password
        ):
            return JSONResponse(
                {"detail": "authentication required"},
                status_code=401,
                headers=_CHALLENGE,
            )
        return await call_next(request)
