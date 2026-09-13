"""FastAPI application (Phase 3).

Serves the review/journal API. In dev the React frontend runs on Vite and calls
this API (CORS is open in dev). In prod the built frontend can be served by any
static host or reverse proxy.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, candidates, journal


def create_app() -> FastAPI:
    app = FastAPI(title="PokeScanner", version="0.3.0")

    # Dev convenience: allow the Vite dev server. Tighten for production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(candidates.router)
    app.include_router(journal.router)
    app.include_router(analytics.router)
    return app


app = create_app()
