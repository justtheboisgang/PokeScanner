"""ReferenceValue = BERECHNET (§5, §6).

cascade_level und sample_size sind PFLICHT: sonst lässt sich ein schiefer Deal
nicht von einem schlechten Referenzwert unterscheiden. `currency` bleibt im
Schema (V1 immer EUR), damit ebay.com/USD später ohne Migration nachrüstbar ist.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ReferenceSource
from app.models.sa_types import enum_type


class ReferenceValue(Base):
    __tablename__ = "reference_value"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variant.id", ondelete="CASCADE"), index=True
    )

    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    source: Mapped[ReferenceSource] = mapped_column(
        enum_type(ReferenceSource, "referencesource")
    )

    # PFLICHT (§5): which cascade level produced this, on how many data points.
    cascade_level: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    # Stufe 4 (TCGdex) is explicitly a weak reference (§6).
    is_weak: Mapped[bool] = mapped_column(Boolean, default=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    variant: Mapped["Variant"] = relationship(  # noqa: F821
        back_populates="reference_values"
    )
