"""eBay Browse item normalization (§4.3)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.ingest.normalized import NormalizedListing
from app.models.enums import Channel, SellerType


def _price(item: dict) -> tuple[Decimal | None, str]:
    price = item.get("price")
    if isinstance(price, dict):
        try:
            value = Decimal(str(price.get("value")))
        except (InvalidOperation, ValueError, TypeError):
            value = None
        return value, str(price.get("currency") or "EUR")
    return None, "EUR"


def _images(item: dict) -> list[str]:
    urls: list[str] = []
    image = item.get("image")
    if isinstance(image, dict) and image.get("imageUrl"):
        urls.append(str(image["imageUrl"]))
    for extra in item.get("thumbnailImages") or []:
        if isinstance(extra, dict) and extra.get("imageUrl"):
            urls.append(str(extra["imageUrl"]))
    for extra in item.get("additionalImages") or []:
        if isinstance(extra, dict) and extra.get("imageUrl"):
            urls.append(str(extra["imageUrl"]))
    # De-dup while preserving order.
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def _location(item: dict) -> str | None:
    loc = item.get("itemLocation")
    if not isinstance(loc, dict):
        return None
    parts = [loc.get("postalCode"), loc.get("city"), loc.get("country")]
    joined = " ".join(str(p) for p in parts if p)
    return joined or None


def item_country(item: dict) -> str | None:
    """Das Herkunftsland des Angebots, so wie eBay es meldet."""
    loc = item.get("itemLocation")
    if not isinstance(loc, dict):
        return None
    country = loc.get("country")
    return str(country).strip().upper() if country else None


def normalize_ebay_item(item: dict) -> NormalizedListing | None:
    """Map an eBay Browse itemSummary to a NormalizedListing."""
    ext = item.get("itemId") or item.get("legacyItemId")
    title = item.get("title")
    if not ext or not title:
        return None
    value, currency = _price(item)
    return NormalizedListing(
        channel=Channel.EBAY_BROWSE,
        external_id=str(ext),
        title=str(title),
        description=None,  # Browse summary carries no description
        price=value,
        currency=currency,
        location=_location(item),
        seller_type=SellerType.UNKNOWN,
        images=_images(item),
        url=item.get("itemWebUrl"),
        raw_payload=item,
    )
