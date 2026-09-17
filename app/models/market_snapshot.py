"""MarketSnapshot: was der Markt zum Zeitpunkt der Bewertung verlangt hat.

Bewusst NEBEN dem Referenzwert gespeichert, nicht darin. Der Referenzwert steht
auf echten Verkäufen (Stufe 1-3); dieser Datensatz hält fest, was Cardmarket und
TCGPlayer zur selben Zeit als Preis ausgewiesen haben.

Erst beides zusammen macht die eigentlich interessante Zahl messbar: die Lücke
zwischen "wurde wirklich gezahlt" und "soll angeblich kosten". Genau wie die
Zustands- und Sprachfaktoren soll dieser Abstand gemessen und nicht geraten
werden — und er sagt, wie viel ein Cardmarket-Preis überhaupt wert ist.

Währungen bleiben getrennt: cm_* ist EUR, tcg_* ist USD. Keine Umrechnung (§6).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

_Money = Numeric(12, 2)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variant.id", ondelete="CASCADE"), index=True
    )
    # The sold-based value computed in the same breath, when there was one.
    reference_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_value.id", ondelete="SET NULL"), index=True
    )

    # Cardmarket (EUR).
    cm_avg: Mapped[Decimal | None] = mapped_column(_Money)
    cm_low: Mapped[Decimal | None] = mapped_column(_Money)
    cm_trend: Mapped[Decimal | None] = mapped_column(_Money)
    cm_avg7: Mapped[Decimal | None] = mapped_column(_Money)
    cm_avg30: Mapped[Decimal | None] = mapped_column(_Money)
    # TCGPlayer (USD) — never converted, never mixed into a valuation.
    tcg_market_usd: Mapped[Decimal | None] = mapped_column(_Money)
    tcg_low_usd: Mapped[Decimal | None] = mapped_column(_Money)

    source: Mapped[str] = mapped_column(String(32), default="pokewallet")
    source_card_id: Mapped[str | None] = mapped_column(String(128))
    variant_label: Mapped[str | None] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    reference_value: Mapped["ReferenceValue | None"] = relationship(  # noqa: F821
        "ReferenceValue"
    )
