"""Kleinanzeigen normalization (§4.4).

The exact Apify actor is user-configured, so field mapping is defensive: several
candidate keys are tried per field, and the full raw item is preserved in
`raw_payload`. Tune the key lists to your chosen actor if needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.models.enums import SellerType

# Free-giveaway phrases -> price 0 (a free Konvolut can be a real find).
_FREE_MARKERS = ("zu verschenken", "verschenke", "kostenlos", "gratis", "free")

_ID_KEYS = ("adId", "id", "listingId", "externalId")
_TITLE_KEYS = ("title", "name", "heading")
_DESC_KEYS = ("description", "text", "body")
_PRICE_KEYS = ("price", "priceText", "priceLabel", "priceValue")
_LOCATION_KEYS = ("location", "locationName", "city", "address", "zip")
_URL_KEYS = ("url", "link", "adUrl", "href")
_IMAGE_KEYS = ("images", "imageUrls", "imageUrl", "image", "photos", "thumbnails")
_SELLER_KEYS = ("sellerType", "seller_type", "commercial", "isCommercial", "type")
_CONDITION_KEYS = ("condition", "zustand", "Zustand")
_DATE_KEYS = ("date", "postedDate", "postedAt", "createdAt", "publishedAt")

_NUM_RE = re.compile(r"\d[\d.\s]*(?:,\d+)?")


@dataclass
class NormalizedListing:
    external_id: str
    title: str
    description: str | None
    price: Decimal | None
    currency: str
    location: str | None
    seller_type: SellerType
    images: list[str]
    url: str | None
    raw_payload: dict = field(default_factory=dict)


def _first(item: dict, keys: tuple[str, ...]) -> object:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


def parse_price(raw: object) -> Decimal | None:
    """Parse a German price string. 'VB'/empty -> None, 'Zu verschenken' -> 0."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    text = str(raw).strip().lower()
    if not text:
        return None
    if any(marker in text for marker in _FREE_MARKERS):
        return Decimal("0")
    match = _NUM_RE.search(text)
    if not match:
        return None  # e.g. "VB", "auf anfrage"
    num = match.group(0)
    # German formatting: '.' thousands, ',' decimal.
    num = num.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        value = Decimal(num)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def parse_seller_type(raw: object) -> SellerType:
    if raw is None:
        return SellerType.UNKNOWN
    if isinstance(raw, bool):
        return SellerType.COMMERCIAL if raw else SellerType.PRIVATE
    text = str(raw).strip().lower()
    if text in ("private", "privat", "private_seller", "false"):
        return SellerType.PRIVATE
    if text in ("commercial", "gewerblich", "business", "true", "dealer"):
        return SellerType.COMMERCIAL
    return SellerType.UNKNOWN


def _images(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        out: list[str] = []
        for entry in raw:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict):
                u = entry.get("url") or entry.get("src") or entry.get("large")
                if u:
                    out.append(str(u))
        return out
    return []


def normalize(item: dict) -> NormalizedListing | None:
    """Map a raw actor item to a NormalizedListing. None if no id or title."""
    ext = _first(item, _ID_KEYS)
    url = _first(item, _URL_KEYS)
    if ext is None and url is not None:
        ext = url  # fall back to URL as the dedup key
    title = _first(item, _TITLE_KEYS)
    if ext is None or title is None:
        return None

    return NormalizedListing(
        external_id=str(ext),
        title=str(title),
        description=(str(_first(item, _DESC_KEYS)) if _first(item, _DESC_KEYS) else None),
        price=parse_price(_first(item, _PRICE_KEYS)),
        currency="EUR",
        location=(str(_first(item, _LOCATION_KEYS)) if _first(item, _LOCATION_KEYS) else None),
        seller_type=parse_seller_type(_first(item, _SELLER_KEYS)),
        images=_images(_first(item, _IMAGE_KEYS)),
        url=(str(url) if url else None),
        raw_payload=item,
    )


def build_run_input(query: str) -> dict:
    """Build the actor input for one search term.

    Generic shape (`search`/`query`/`keyword` all set) so it fits common
    Kleinanzeigen actors without per-actor branching. Adjust for your actor.
    """
    return {"search": query, "query": query, "keyword": query}
