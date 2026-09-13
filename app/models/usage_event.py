"""UsageEvent: real API call counts per source, per poll (§9 Kosten).

Records actual usage (call counts). Cost is derived in the API from configurable
per-call estimates — never fabricated (R3): if no unit cost is set, only usage is
shown, not a euro figure.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UsageEvent(Base):
    __tablename__ = "usage_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Source key: "kleinanzeigen", "willhaben", "ebay_browse", "vision", ...
    source: Mapped[str] = mapped_column(String(64), index=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
