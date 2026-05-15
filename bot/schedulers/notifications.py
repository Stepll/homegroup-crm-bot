from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from bot.api_client import api_client

logger = logging.getLogger(__name__)

KYIV = ZoneInfo("Europe/Kyiv")

# Ukrainian day names → Python weekday (Mon=0 … Sun=6)
MEETING_DAY_MAP: dict[str, int] = {
    "Понеділок": 0,
    "Вівторок": 1,
    "Середа": 2,
    "Четвер": 3,
    "Пʼятниця": 4,
    "П'ятниця": 4,
    "Субота": 5,
    "Неділя": 6,
}

# (group_id, date_str) — avoid double-trigger within the same day
_triggered: set[tuple[int, str]] = set()


async def check_auto_attendance(bot: Bot) -> None:
    from bot.handlers.attendance import start_attendance_flow

    now = datetime.now(KYIV)
    today_str = now.strftime("%Y-%m-%d")
    today_weekday = now.weekday()
    current_minutes = now.hour * 60 + now.minute

    try:
        groups = await api_client.get_groups()
    except Exception:
        logger.exception("check_auto_attendance: failed to fetch groups")
        return

    for group in groups:
        tg_id = group.get("telegramGroupId")
        meeting_day = group.get("meetingDay")
        meeting_time = group.get("meetingTime")
        if not tg_id or not meeting_day or not meeting_time:
            continue

        weekday = MEETING_DAY_MAP.get(meeting_day)
        if weekday is None or weekday != today_weekday:
            continue

        try:
            h, m = map(int, meeting_time.split(":"))
        except Exception:
            continue

        # Trigger window: meetingTime + 60 min, ±3 min
        trigger_minutes = h * 60 + m + 60
        if abs(current_minutes - trigger_minutes) > 3:
            continue

        group_id = group["id"]
        key = (group_id, today_str)
        if key in _triggered:
            continue
        _triggered.add(key)

        try:
            await start_attendance_flow(bot, group_id, tg_id, today_str)
            logger.info("Auto attendance triggered for group %s on %s", group_id, today_str)
        except Exception:
            logger.exception("Failed to start auto attendance for group %s", group_id)


async def notify_upcoming_events(bot: Bot) -> None:
    # TODO: fetch groups, check upcoming events, send notifications
    logger.info("notify_upcoming_events triggered")


async def notify_meeting_plan(bot: Bot) -> None:
    # TODO: send plan day before meeting
    logger.info("notify_meeting_plan triggered")


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    # Auto attendance — check every minute
    scheduler.add_job(
        check_auto_attendance,
        trigger="cron",
        minute="*",
        kwargs={"bot": bot},
        id="check_auto_attendance",
    )
    # Notify about upcoming events — every day at 09:00
    scheduler.add_job(
        notify_upcoming_events,
        trigger="cron",
        hour=9,
        minute=0,
        kwargs={"bot": bot},
        id="notify_upcoming_events",
    )
    # Send meeting plan — every day at 18:00
    scheduler.add_job(
        notify_meeting_plan,
        trigger="cron",
        hour=18,
        minute=0,
        kwargs={"bot": bot},
        id="notify_meeting_plan",
    )
