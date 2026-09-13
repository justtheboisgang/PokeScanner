"""ReferenceComp: the individual comps behind a reference value (§9).

The website must show each comp that produced a reference value, individually and
verifiable. The §5 core model had no comp table; this adds it (Phase 3). Ask
listings are NOT stored here — they are never counted as sales (§9).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Condition, Language
from app.models.sa_types import enum_type


class ReferenceComp(Base):
    __tablename__ = "reference_comp"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_value_id: Mapped[int] = mapped_column(
        ForeignKey("reference_value.id", ondelete="CASCADE"), index=True
    )

    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[Language] = mapped_column(enum_type(Language, "language"))
    condition: Mapped[Condition] = mapped_column(enum_type(Condition, "condition"))
    # Whether soldPrice was BOA-hydrated (real paid price, not the ask) — §4.2.2.
    boa_hydrated: Mapped[bool] = mapped_column(Boolean, default=False)
    epid: Mapped[str | None] = mapped_column(String(64))
    source_item_id: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    reference_value: Mapped["ReferenceValue"] = relationship(  # noqa: F821
        back_populates="comps"
    )
