"""Kleinanzeigen normalization (§4.4).

The exact Apify actor is user-configured, so field mapping is defensive: several
candidate keys are tried per field, and the full raw item is preserved in
`raw_payload`. Tune the key lists to your chosen actor if needed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app.ingest.normalized import NormalizedListing
from app.models.enums import Channel, SellerType

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


def normalize_apify_item(item: dict, channel: Channel) -> NormalizedListing | None:
    """Map a raw Apify item to a NormalizedListing. None if no id or title.

    Shared by the Kleinanzeigen and willhaben sources — both actors expose the
    same rough field shapes; the key lists above are tried defensively.
    """
    ext = _first(item, _ID_KEYS)
    url = _first(item, _URL_KEYS)
    if ext is None and url is not None:
        ext = url  # fall back to URL as the dedup key
    title = _first(item, _TITLE_KEYS)
    if ext is None or title is None:
        return None

    return NormalizedListing(
        channel=channel,
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


def normalize(item: dict) -> NormalizedListing | None:
    """Normalize a Kleinanzeigen actor item (generic fallback)."""
    return normalize_apify_item(item, Channel.KLEINANZEIGEN)


def _plain_decimal(value: object) -> Decimal | None:
    """Parse a plain decimal string like '59.00' (English decimal point)."""
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d >= 0 else None


_REL_RE = re.compile(r"vor\s+(\d+)\s+(minute|minuten|stunde|stunden|tag|tagen)", re.I)


def parse_listed_at(
    value: object, *, now: datetime | None = None
) -> tuple[datetime | None, str]:
    """Parse a Kleinanzeigen posting date into (datetime_utc, precision).

    Handles absolute 'DD.MM.YYYY' (precision 'day'), 'Heute'/'Gestern' and
    relative 'vor X Stunden/Minuten/Tagen'. Unrecognized -> (None, 'unknown').
    """
    now = now or datetime.now(timezone.utc)
    if value is None:
        return None, "unknown"
    text = str(value).strip().lower()
    if not text:
        return None, "unknown"

    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc), "day"
        except ValueError:
            return None, "unknown"

    if text.startswith("heute"):
        return now.replace(hour=0, minute=0, second=0, microsecond=0), "day"
    if text.startswith("gestern"):
        return (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ), "day"

    rel = _REL_RE.search(text)
    if rel:
        n = int(rel.group(1))
        unit = rel.group(2)
        if unit.startswith("minute"):
            return now - timedelta(minutes=n), "minute"
        if unit.startswith("stunde"):
            return now - timedelta(hours=n), "hour"
        return now - timedelta(days=n), "day"

    return None, "unknown"


def normalize_lexis_item(item: dict) -> NormalizedListing | None:
    """Normalize an item from lexis-solutions/ebay-kleinanzeigen.

    Field names taken from that actor's documented output; prices are plain
    decimal strings ("59.00"), so they are parsed directly (not via the German
    thousands/decimal parser).
    """
    ext = item.get("id") or item.get("url")
    title = item.get("title")
    if ext is None or not title:
        return None

    images: list[str] = []
    primary = item.get("primaryImageURL")
    if primary:
        images.append(str(primary))
    for url in item.get("imageURLs") or []:
        if url and str(url) not in images:
            images.append(str(url))

    # A private Kleinanzeigen seller has no companyInfo block.
    seller_type = (
        SellerType.COMMERCIAL if item.get("companyInfo") else SellerType.PRIVATE
    )

    listed_at, precision = parse_listed_at(item.get("date"))

    return NormalizedListing(
        channel=Channel.KLEINANZEIGEN,
        external_id=str(ext),
        title=str(title),
        description=(
            str(item["descriptionText"]) if item.get("descriptionText") else None
        ),
        price=_plain_decimal(item.get("price")),
        currency=str(item.get("priceCurrency") or "EUR"),
        location=(str(item["address"]) if item.get("address") else None),
        seller_type=seller_type,
        images=images,
        url=(str(item["url"]) if item.get("url") else None),
        listed_at=listed_at,
        listed_at_precision=precision,
        raw_payload=item,
    )


def build_kleinanzeigen_search_url(query: str) -> str:
    """A Kleinanzeigen keyword search-results URL for a term."""
    slug = re.sub(r"[^a-z0-9]+", "-", query.strip().lower()).strip("-")
    return f"https://www.kleinanzeigen.de/s-{slug}/k0"


def build_run_input(query: str, template: str | None = None) -> dict:
    """Build the actor input for one search term.

    If `template` (JSON) is given, placeholders are substituted:
      - "{{query}}"      -> the raw search term
      - "{{search_url}}" -> a Kleinanzeigen search-results URL for the term
    This lets you match any actor's schema via config. Without a template, a
    generic keyword shape (`search`/`query`/`keyword`) is used.
    """
    if template and template.strip():
        q = json.dumps(query)[1:-1]  # JSON-escaped, without surrounding quotes
        url = json.dumps(build_kleinanzeigen_search_url(query))[1:-1]
        filled = template.replace("{{query}}", q).replace("{{search_url}}", url)
        return json.loads(filled)
    return {"search": query, "query": query, "keyword": query}
