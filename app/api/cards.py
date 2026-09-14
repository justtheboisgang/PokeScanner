"""Card lookup endpoints (TCGdex autocomplete for manual evaluation, Block 2.3)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.api.schemas import TcgdexCardOut
from app.clients.tcgdex import TCGdexClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tcgdex", tags=["tcgdex"])


def _image(item: dict) -> str | None:
    img = item.get("image")
    if not img:
        return None
    # TCGdex brief images are a base URL; append a quality + format for display.
    return f"{img}/low.webp"


@router.get("/search", response_model=list[TcgdexCardOut])
def search(
    q: str = Query(..., min_length=2),
    lang: str = Query("de"),
) -> list[TcgdexCardOut]:
    try:
        results = TCGdexClient(primary_lang=lang).search_cards(q, lang)
    except Exception:
        logger.exception("tcgdex search failed for %r", q)
        return []
    out: list[TcgdexCardOut] = []
    for item in results:
        cid = item.get("id")
        name = item.get("name")
        if cid and name:
            out.append(TcgdexCardOut(id=str(cid), name=str(name), image=_image(item)))
    return out
