"""Health check (Block 4): schlägt Alarm, wenn der Scanner still geworden ist.

Ein 24/7-Messinstrument, das unbemerkt stehenbleibt, ist schlimmer als keines —
man verlässt sich darauf. Jeder abgeschlossene Poll schreibt einen Heartbeat;
liegt der letzte länger zurück als das erlaubte Schweigefenster, geht eine
Warnung an Discord. Die Warnung hat einen eigenen Cooldown, damit ein dauerhaft
toter Worker nicht im Minutentakt spammt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.discord import DiscordNotifier
from app.config import Settings, get_settings
from app.db import session_scope
from app.models.usage_event import UsageEvent

logger = logging.getLogger(__name__)

# Heartbeat written by the pipeline after every completed poll.
HEARTBEAT_SOURCE = "poll_heartbeat"
# Marker row so a dead worker is not reported over and over.
WARNING_SOURCE = "health_warning"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class HealthMonitor:
    def __init__(
        self,
        notifier: DiscordNotifier,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
        settings: Settings | None = None,
    ) -> None:
        self.notifier = notifier
        self.session_factory = session_factory
        self.settings = settings or get_settings()

    def _last(self, source: str) -> datetime | None:
        with self.session_factory() as session:
            value = session.scalar(
                select(func.max(UsageEvent.recorded_at)).where(
                    UsageEvent.source == source
                )
            )
        return _aware(value)

    def last_poll_at(self) -> datetime | None:
        return self._last(HEARTBEAT_SOURCE)

    def silence(self, now: datetime | None = None) -> timedelta | None:
        """How long the scanner has been quiet, or None if it never ran."""
        last = self.last_poll_at()
        if last is None:
            return None
        return (now or datetime.now(timezone.utc)) - last

    def is_stale(self, now: datetime | None = None) -> bool:
        quiet = self.silence(now)
        if quiet is None:
            # Never polled: nothing to compare against, so not "stale" yet.
            return False
        return quiet >= timedelta(hours=self.settings.health_max_silence_hours)

    def _recently_warned(self, now: datetime | None = None) -> bool:
        last = self._last(WARNING_SOURCE)
        if last is None:
            return False
        cooldown = timedelta(hours=self.settings.health_warn_cooldown_hours)
        return (now or datetime.now(timezone.utc)) - last < cooldown

    def _mark_warned(self, when: datetime) -> None:
        # Write the same clock the decision used, so the cooldown is consistent
        # (and testable) instead of mixing app time with the DB's now().
        with self.session_factory() as session:
            session.add(UsageEvent(source=WARNING_SOURCE, calls=1, recorded_at=when))

    def check(self, now: datetime | None = None) -> bool:
        """Warn on Discord if the scanner is quiet. Returns True if it warned."""
        if not self.settings.health_check_enabled:
            return False
        now = now or datetime.now(timezone.utc)
        if not self.is_stale(now):
            return False
        if self._recently_warned(now):
            return False

        quiet = self.silence(now)
        hours = quiet.total_seconds() / 3600 if quiet else 0
        message = (
            f"⚠️ PokeScanner: seit {hours:.1f} h kein erfolgreicher Scan "
            f"(Grenze {self.settings.health_max_silence_hours} h). "
            "Läuft der Worker noch?"
        )
        try:
            self.notifier.send_text(message)
        except Exception:
            logger.exception("failed to send health warning")
            return False
        self._mark_warned(now)
        logger.warning("health warning sent: quiet for %.1f h", hours)
        return True
