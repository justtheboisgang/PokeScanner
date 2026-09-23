"""Auktionen, die bald enden (§ Auktions-Wache).

Eine Auktion ist erst kurz vor Schluss eine Information: bis dahin steigt der
Preis, und was dreissig Minuten vorher guenstig aussieht, ist es am Ende oft
nicht mehr. Deshalb werden Auktionen frueh ERFASST und bewertet — der teure
Teil passiert in Ruhe —, aber erst kurz vor Ablauf mit dem aktuellen Gebot
verglichen und gemeldet.

Der Vergleichswert stammt bewusst aus Marktpreisen (kostenlos, sofort
verfuegbar) und nicht aus Verkaufsdaten: eine Auktionsmeldung, die zwei
Minuten zu spaet kommt, ist wertlos.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuctionWatch(Base):
    __tablename__ = "auction_watch"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_auction_watch_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000))
    image: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str] = mapped_column(String(8), default="EUR")

    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Vergleichswert und woher er kommt — ohne die Herkunft ist eine Zahl
    # wertlos, weil Marktpreis und Verkaufspreis zweierlei sind.
    reference_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reference_source: Mapped[str | None] = mapped_column(String(32))
    card_name: Mapped[str | None] = mapped_column(String(200))
    card_number: Mapped[str | None] = mapped_column(String(32))
    # Warum diese Auktion NICHT ueberwacht wird (nicht aufloesbar, Sprache,
    # kein Marktpreis). Sonst steht sie stumm in der Tabelle.
    skip_reason: Mapped[str | None] = mapped_column(String(200))

    matched_search_term: Mapped[str | None] = mapped_column(String(255))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
