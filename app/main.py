"""FastAPI application (Phase 3).

Serves the review/journal API. In dev the React frontend runs on Vite and calls
this API (CORS is open in dev). In prod the built frontend can be served by any
static host or reverse proxy.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, candidates, cards, journal, trades
from app.api.auth import BasicAuthMiddleware
from app.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="PokeScanner", version="0.4.0")

    settings = get_settings()

    # Passwortschutz (Block 4): nur aktiv, wenn WEB_PASSWORD gesetzt ist.
    # Muss VOR CORS registriert werden, damit CORS-Header auch auf 401 sitzen.
    if settings.web_password:
        app.add_middleware(
            BasicAuthMiddleware,
            username=settings.web_username,
            password=settings.web_password,
        )

    # CORS origins from config ("*" for dev; set CORS_ALLOW_ORIGINS in prod).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(candidates.router)
    app.include_router(cards.router)
    app.include_router(journal.router)
    app.include_router(analytics.router)
    app.include_router(trades.router)
    return app


app = create_app()
