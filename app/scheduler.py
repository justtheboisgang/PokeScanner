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

from app.config import Settings, get_settings
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
    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_timezone)

    pipeline = build_pipeline(settings=settings)

    scheduler = BlockingScheduler(timezone=tz)
    day_trigger, night_trigger = build_triggers(settings, tz)
    scheduler.add_job(pipeline.poll, day_trigger, id="poll_day", max_instances=1)
    scheduler.add_job(pipeline.poll, night_trigger, id="poll_night", max_instances=1)

    logger.info(
        "scheduler starting (tz=%s, day %02d:00-%02d:00 every %dm, night every %dm)",
        settings.scheduler_timezone,
        settings.poll_day_start_hour,
        settings.poll_day_end_hour,
        settings.poll_day_interval_minutes,
        settings.poll_night_interval_minutes,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopped")


if __name__ == "__main__":
    run()
