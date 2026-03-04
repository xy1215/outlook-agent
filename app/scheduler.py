from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def create_scheduler(timezone_name: str) -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=timezone_name)


def parse_schedule_time(schedule_time: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = (schedule_time or "").split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid SCHEDULE_TIME '{schedule_time}': expected HH:MM format") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid SCHEDULE_TIME '{schedule_time}': hour must be 0-23, minute 0-59")
    return hour, minute


def daily_trigger(schedule_time: str, timezone_name: str) -> CronTrigger:
    hour, minute = parse_schedule_time(schedule_time)
    return CronTrigger(hour=hour, minute=minute, timezone=timezone_name)
