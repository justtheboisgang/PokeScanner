"""APScheduler worker (Phase 2, §3/§11).

Staggered poll: every `poll_day_interval_minutes` during the day window
[day_start, day_end), and every `poll_night_interval_minutes` otherwise. Both
values and the window are configurable.

This is the Phase 2 runtime entrypoint — there is no web server yet.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.alerts.discord import DiscordNotifier
from app.auctions import AuctionWatcher
from app.config import Settings, get_settings
from app.health import HealthMonitor
from app.ingest.pipeline import build_pipeline

logger = logging.getLogger(__name__)


def night_hours(day_start: int, day_end: int) -> list[int]:
    """Hours (0-23) that fall OUTSIDE the day window [day_start, day_end)."""
    day = set(range(day_start, day_end))
    return [h for h in range(24) if h not in day]


def _minute_spec(interval_minutes: int) -> str:
    return "0" if interval_minutes >= 60 else f"*/{interval_minutes}"


def build_triggers(settings: Settings, tz: ZoneInfo) -> tuple[CronTrigger, CronTrigger]:
    """Build (day_trigger, night_trigger) from settings."""
    day = CronTrigger(
        hour=f"{settings.poll_day_start_hour}-{settings.poll_day_end_hour - 1}",
        minute=_minute_spec(settings.poll_day_interval_minutes),
        timezone=tz,
    )
    nights = night_hours(settings.poll_day_start_hour, settings.poll_day_end_hour)
    night = CronTrigger(
        hour=",".join(str(h) for h in nights),
        minute=_minute_spec(settings.poll_night_interval_minutes),
        timezone=tz,
    )
    return day, night


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_timezone)

    pipeline = build_pipeline(settings=settings)

    scheduler = BlockingScheduler(timezone=tz)
    day_trigger, night_trigger = build_triggers(settings, tz)
    scheduler.add_job(pipeline.poll, day_trigger, id="poll_day", max_instances=1)
    scheduler.add_job(pipeline.poll, night_trigger, id="poll_night", max_instances=1)

    # Auktions-Wache: zwei Takte, weil beide Haelften verschiedene
    # Anforderungen haben. Das Suchen darf dauern, das Pruefen kurz vor
    # Ablauf nicht — und eine Meldung, die zwei Minuten zu spaet kommt, ist
    # wertlos, deshalb laeuft der Pruef-Takt minuetlich.
    if settings.auction_watch_enabled and settings.ebay_browse_enabled:
        watcher = AuctionWatcher(settings=settings)
        scheduler.add_job(
            watcher.scan,
            CronTrigger(
                minute=_minute_spec(settings.auction_scan_interval_minutes), timezone=tz
            ),
            id="auction_scan",
            max_instances=1,
        )
        scheduler.add_job(
            watcher.tick,
            CronTrigger(minute="*", timezone=tz),
            id="auction_tick",
            max_instances=1,
        )

    # Health check (Block 4): stündlich prüfen, ob überhaupt noch gescannt wird.
    if settings.health_check_enabled:
        monitor = HealthMonitor(DiscordNotifier(), settings=settings)
        scheduler.add_job(
            monitor.check,
            CronTrigger(minute=17, timezone=tz),
            id="health_check",
            max_instances=1,
        )

    logger.info(
        "scheduler starting (tz=%s, day %02d:00-%02d:00 every %dm, night every %dm, "
        "health check %s, Auktions-Wache %s)",
        settings.scheduler_timezone,
        settings.poll_day_start_hour,
        settings.poll_day_end_hour,
        settings.poll_day_interval_minutes,
        settings.poll_night_interval_minutes,
        f"after {settings.health_max_silence_hours}h silence"
        if settings.health_check_enabled
        else "off",
        f"{settings.auction_window_minutes}min-Fenster, Alarm "
        f"{settings.auction_alert_lead_minutes}min vor Schluss ab "
        f"{settings.auction_min_discount_pct}% Abstand"
        if settings.auction_watch_enabled and settings.ebay_browse_enabled
        else "aus",
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopped")


if __name__ == "__main__":
    run()
