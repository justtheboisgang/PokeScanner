"""Listing = ROHDATEN (§5).

Raw, un-interpreted data as pulled from a channel. `raw_payload` keeps the full
original response so nothing is lost. `image_hash` is reserved for cross-channel
dedup (Bildhash + Preis + Ort) — the dedup *logic* lands in Phase 2.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Postgres gets ARRAY/JSONB; other backends (e.g. SQLite in tests) fall back to
# JSON. The migrations remain Postgres-native (ARRAY/JSONB).
_ImageList = JSON().with_variant(ARRAY(Text), "postgresql")
_RawPayload = JSON().with_variant(JSONB, "postgresql")

from app.db import Base
from app.models.enums import Channel, SellerType
from app.models.sa_types import enum_type


class Listing(Base):
    __tablename__ = "listing"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[Channel] = mapped_column(enum_type(Channel, "channel"), index=True)
    # Channel-native id (e.g. eBay itemId, Kleinanzeigen ad id).
    external_id: Mapped[str] = mapped_column(String(255), index=True)

    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    location: Mapped[str | None] = mapped_column(String(255))
    seller_type: Mapped[SellerType] = mapped_column(
        enum_type(SellerType, "sellertype"), default=SellerType.UNKNOWN
    )

    images: Mapped[list[str]] = mapped_column(_ImageList, default=list)
    # Heuristic dedup key across channels (Phase 2). People cross-post.
    image_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    url: Mapped[str | None] = mapped_column(Text)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    raw_payload: Mapped[dict] = mapped_column(_RawPayload, default=dict)

    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_listing_channel_external"),
    )
