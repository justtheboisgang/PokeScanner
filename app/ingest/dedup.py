"""Cross-channel dedup via image hash + price + location (§5).

People cross-post the same physical ad across channels. To avoid double-alerting,
an alerting candidate's first image is average-hashed (aHash); if an already-
alerted listing on another listing has the same hash and a price within tolerance,
the new one is treated as a duplicate and does not alert.

Image download is done only for alerting candidates (bounded), never for every
fetched listing (R2 spirit).
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.listing import Listing

logger = logging.getLogger(__name__)

_HASH_SIZE = 8  # 8x8 => 64-bit aHash


def compute_ahash(image_bytes: bytes) -> str:
    """Average hash (aHash) of an image, as 16 hex chars. Requires Pillow."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        small = img.convert("L").resize((_HASH_SIZE, _HASH_SIZE))
        pixels = list(small.tobytes())  # 64 grayscale byte values
    avg = sum(pixels) / len(pixels)
    bits = 0
    for px in pixels:
        bits = (bits << 1) | (1 if px >= avg else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    """Hamming distance between two hex aHash strings."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class ImageHasher:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
        max_bytes: int = 5_000_000,
    ) -> None:
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
        self.max_bytes = max_bytes

    def close(self) -> None:
        self._client.close()

    def hash_url(self, url: str) -> str | None:
        """Download and hash an image. None on any failure (never raises)."""
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            data = resp.content[: self.max_bytes]
            return compute_ahash(data)
        except Exception:
            logger.info("image hash failed for %s", url, exc_info=True)
            return None


def find_duplicate_listing(
    session: Session,
    *,
    image_hash: str,
    price: Decimal | None,
    exclude_listing_id: int,
    price_tolerance: Decimal,
) -> Listing | None:
    """Return an already-alerted listing that matches this one, else None.

    Match = identical aHash AND (both prices missing, or within tolerance). Only
    listings that already produced a candidate count (we dedup against alerts).
    """
    stmt = (
        select(Listing)
        .join(Candidate, Candidate.listing_id == Listing.id)
        .where(
            Listing.image_hash == image_hash,
            Listing.id != exclude_listing_id,
        )
    )
    for other in session.scalars(stmt).unique():
        if price is None or other.price is None:
            if price is None and other.price is None:
                return other
            continue
        if abs(Decimal(other.price) - Decimal(price)) <= price_tolerance:
            return other
    return None
