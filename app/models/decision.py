"""Decision = URTEIL (§5).

Rejected listings ARE stored, with verdict + reason: ohne Negativbeispiele lässt
sich später nie messen, ob der Filter zu eng oder zu breit läuft (§5).
Fälschungsprüfung ist ein explizites Pflichtfeld (§7).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import CounterfeitCheck, Verdict
from app.models.sa_types import enum_type


class Decision(Base):
    __tablename__ = "decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), unique=True, index=True
    )

    verdict: Mapped[Verdict] = mapped_column(enum_type(Verdict, "verdict"))
    reason: Mapped[str | None] = mapped_column(Text)
    # Mandatory counterfeit-check step (§7). Im Zweifel: nicht kaufen.
    counterfeit_check: Mapped[CounterfeitCheck] = mapped_column(
        enum_type(CounterfeitCheck, "counterfeitcheck"),
        default=CounterfeitCheck.NOT_CHECKED,
    )

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Time-to-decision from the alert — a core calibration metric (§9).
    seconds_since_alert: Mapped[int | None] = mapped_column(Integer)

    candidate: Mapped["Candidate"] = relationship(  # noqa: F821
        back_populates="decision"
    )
