"""CandidateCard: a card the operator identified inside a listing (Block 2.3).

Manual identification is the operator's job (they look at the photo). Each entry
links a candidate to a variant and the reference value computed for it, so a
Konvolut can hold several cards. This is also training data: title -> what was
actually inside.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CandidateCard(Base):
    __tablename__ = "candidate_card"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int] = mapped_column(ForeignKey("variant.id", ondelete="CASCADE"))
    reference_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_value.id", ondelete="SET NULL")
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # "manual" = vom Operator eingetragen, "auto" = vom Titel-Resolver.
    # Die Automatik darf Handarbeit nie ueberschreiben — einen abgebrochenen
    # eigenen Versuch aber sehr wohl wiederholen. Ohne diese Unterscheidung
    # blockierte ein gescheiterter Lauf die Karte fuer immer.
    source: Mapped[str] = mapped_column(String(16), default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    variant: Mapped["Variant"] = relationship("Variant")  # noqa: F821
    reference_value: Mapped["ReferenceValue | None"] = relationship(  # noqa: F821
        "ReferenceValue"
    )
    candidate: Mapped["Candidate"] = relationship(  # noqa: F821
        back_populates="cards"
    )
