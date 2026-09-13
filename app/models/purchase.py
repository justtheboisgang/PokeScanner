"""Purchase & Sale (§5).

Purchase carries the mandatory §25a UStG (Differenzbesteuerung) fields. These are
NOT NULL: without complete acquisition data the accounting is worthless.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Channel
from app.models.sa_types import enum_type


class Purchase(Base):
    __tablename__ = "purchase"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL")
    )

    # §25a UStG mandatory fields — all NOT NULL.
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    date: Mapped[date_type] = mapped_column(Date)
    channel: Mapped[Channel] = mapped_column(enum_type(Channel, "channel"))
    seller_name: Mapped[str] = mapped_column(String(255))
    seller_address: Mapped[str] = mapped_column(Text)

    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    candidate: Mapped["Candidate | None"] = relationship("Candidate")  # noqa: F821
    sale: Mapped["Sale | None"] = relationship(
        back_populates="purchase", uselist=False, cascade="all, delete-orphan"
    )


class Sale(Base):
    __tablename__ = "sale"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchase.id", ondelete="CASCADE"), unique=True, index=True
    )

    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    date: Mapped[date_type] = mapped_column(Date)
    channel: Mapped[Channel] = mapped_column(enum_type(Channel, "channel"))
    fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    days_to_sell: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    purchase: Mapped["Purchase"] = relationship(back_populates="sale")
