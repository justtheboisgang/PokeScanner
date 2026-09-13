"""Channel-agnostic normalized listing (Phase 5).

Every source (Kleinanzeigen, willhaben, eBay Browse, ...) maps its raw items to
this shape so ingestion, dedup, the alarm rule and enrichment are shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models.enums import Channel, SellerType


@dataclass
class NormalizedListing:
    channel: Channel
    external_id: str
    title: str
    description: str | None
    price: Decimal | None
    currency: str
    location: str | None
    seller_type: SellerType
    images: list[str]
    url: str | None
    # When the ad was posted on the channel (§1.2), with a precision marker.
    listed_at: datetime | None = None
    listed_at_precision: str = "unknown"
    raw_payload: dict = field(default_factory=dict)
