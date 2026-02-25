from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def create_scheduler(timezone_name: str) -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=timezone_name)


def parse_schedule_time(schedule_time: str) -> tuple[int, int]:
    hour_str, minute_str = schedule_time.split(":", 1)
    return int(hour_str), int(minute_str)


def daily_trigger(schedule_time: str, timezone_name: str) -> CronTrigger:
    hour, minute = parse_schedule_time(schedule_time)
    return CronTrigger(hour=hour, minute=minute, timezone=timezone_name)
