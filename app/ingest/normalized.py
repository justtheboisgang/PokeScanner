"""Channel-agnostic normalized listing (Phase 5).

Every source (Kleinanzeigen, willhaben, eBay Browse, ...) maps its raw items to
this shape so ingestion, dedup, the alarm rule and enrichment are shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    raw_payload: dict = field(default_factory=dict)
