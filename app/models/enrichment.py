"""Enrichment = advisory hints produced AFTER the alarm (Phase 4, §10/§11).

Text extraction of condition-defect keywords and an optional vision-triage note.
These are HINTS only — never a buy/condition/authenticity verdict, never a price
(§10). Kept in its own table (Rohdaten/berechnet/Urteil bleiben getrennt, §5).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

_JsonList = JSON().with_variant(JSONB, "postgresql")


class Enrichment(Base):
    __tablename__ = "enrichment"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Deterministic keyword hits on condition defects ("knick", "bespielt", ...).
    condition_flags: Mapped[list[str]] = mapped_column(_JsonList, default=list)

    # Optional vision-triage note (advisory text only).
    vision_summary: Mapped[str | None] = mapped_column(Text)
    vision_model: Mapped[str | None] = mapped_column(String(64))
    vision_used: Mapped[bool] = mapped_column(Boolean, default=False)

    enriched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    candidate: Mapped["Candidate"] = relationship(  # noqa: F821
        back_populates="enrichment"
    )
