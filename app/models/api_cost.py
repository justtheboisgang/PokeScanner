"""ApiCost: one row per external API call (Block 0.2 Cost Guard).

Every call to Anthropic / Apify / SoldComps records its estimated cost here, so
the daily per-provider budget can be enforced and cost-per-fund reported.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from app.db import Base


class ApiCost(Base):
    __tablename__ = "api_cost"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    units: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_eur: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), index=True
    )
