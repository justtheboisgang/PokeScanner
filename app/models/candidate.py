"""Candidate = a listing that fired the alert (§5).

`reference_value_id` and `estimated_profit` are nullable on purpose: an alert can
be "unbewertbar" (cascade Stufe 5) and still fire (R4). Enrichment edits the
alert later but never retracts it — abgelehnte Kandidaten sind Kalibrierungsdaten.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Candidate(Base):
    __tablename__ = "candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listing.id", ondelete="CASCADE"), index=True
    )
    reference_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_value.id", ondelete="SET NULL")
    )

    # NULL when unbewertbar (Stufe 5).
    estimated_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    alert_reason: Mapped[str | None] = mapped_column(Text)
    # The taxonomy term that triggered this candidate — enables data-driven
    # rotation of the active query subset (§4.4 calibration).
    matched_search_term: Mapped[str | None] = mapped_column(String(255), index=True)
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Discord message id, so later enrichment can EDIT the embed (R1, §8).
    discord_message_id: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    listing: Mapped["Listing"] = relationship("Listing")  # noqa: F821
    reference_value: Mapped["ReferenceValue | None"] = relationship(  # noqa: F821
        "ReferenceValue"
    )
    decision: Mapped["Decision | None"] = relationship(  # noqa: F821
        back_populates="candidate", uselist=False, cascade="all, delete-orphan"
    )
