"""Card & Variant.

Card = Kartenidentität. Variant = card + language + condition + printing.
Preise hängen IMMER an der Variante, NIE an der Karte (§5).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Condition, Language, Printing
from app.models.sa_types import enum_type


class Card(Base):
    __tablename__ = "card"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    set: Mapped[str | None] = mapped_column(String(255))
    number: Mapped[str | None] = mapped_column(String(64))
    # era is a free string on purpose: alert universe is "alle Ären" (§7).
    era: Mapped[str | None] = mapped_column(String(64), index=True)
    tcgdex_id: Mapped[str | None] = mapped_column(String(128), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    variants: Mapped[list["Variant"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tcgdex_id", name="uq_card_tcgdex_id"),
    )


class Variant(Base):
    __tablename__ = "variant"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("card.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[Language] = mapped_column(
        enum_type(Language, "language"), default=Language.DE
    )
    condition: Mapped[Condition] = mapped_column(
        enum_type(Condition, "condition"), default=Condition.PLAYED
    )
    printing: Mapped[Printing] = mapped_column(
        enum_type(Printing, "printing"), default=Printing.UNKNOWN
    )

    card: Mapped["Card"] = relationship(back_populates="variants")
    reference_values: Mapped[list["ReferenceValue"]] = relationship(  # noqa: F821
        back_populates="variant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "card_id",
            "language",
            "condition",
            "printing",
            name="uq_variant_identity",
        ),
    )
