from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
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

# (group_id, meeting_date) — groups where conflict was already reported
_conflict_notified: set[tuple[int, str]] = set()


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


def _event_matches(event: dict, target: date) -> bool:
    """True if the event falls on target date (year-specific or recurring annual)."""
    try:
        month, day = event["month"], event["day"]
        year = event.get("year")
        if year:
            return date(year, month, day) == target
        # recurring — match month+day regardless of year
        return target.month == month and target.day == day
    except Exception:
        return False


async def notify_upcoming_events(bot: Bot) -> None:
    today = date.today()
    in_7 = today + timedelta(days=7)

    try:
        groups = await api_client.get_groups()
    except Exception:
        logger.exception("notify_upcoming_events: failed to fetch groups")
        return

    for group in groups:
        tg_id = group.get("telegramGroupId")
        if not tg_id:
            continue

        try:
            events = await api_client.get_group_events(group["id"])
        except Exception:
            logger.exception("Failed to fetch events for group %s", group["id"])
            continue

        today_events = [e["name"] for e in events if _event_matches(e, today)]
        week_events = [e["name"] for e in events if _event_matches(e, in_7)]

        lines: list[str] = []
        for name in today_events:
            lines.append(f"🎉 Сьогодні — {name}")
        for name in week_events:
            lines.append(f"📅 Через 7 днів — {name}")

        if lines:
            try:
                await bot.send_message(int(tg_id), "\n".join(lines))
            except Exception:
                logger.exception("Failed to send event notification to %s", tg_id)


async def check_conflicts(bot: Bot, force: bool = False) -> None:
    try:
        groups = await api_client.get_groups()
    except Exception:
        logger.exception("check_conflicts: failed to fetch groups")
        return

    for group in groups:
        tg_id = group.get("telegramGroupId")
        if not tg_id:
            continue

        try:
            cabinet = await api_client.get_cabinet(group["id"])
        except Exception:
            logger.exception("Failed to fetch cabinet for group %s", group["id"])
            continue

        meeting_date = cabinet.get("nextMeetingDate")
        if not meeting_date:
            continue

        conflicts = cabinet.get("nextMeetingConflicts") or []
        has_conflict = len(conflicts) > 0
        key = (group["id"], meeting_date)
        was_notified = key in _conflict_notified

        try:
            if has_conflict and (not was_notified or force):
                _conflict_notified.add(key)
                names = ", ".join(c.get("title", "?") for c in conflicts)
                await bot.send_message(
                    int(tg_id),
                    f"⚠️ Накладка в розкладі — домашка перетинається з: {names}",
                )
            elif not has_conflict and was_notified:
                _conflict_notified.discard(key)
                await bot.send_message(
                    int(tg_id),
                    "✅ Все чисто — домашка більше ні з чим не перетинається",
                )
        except Exception:
            logger.exception("Failed to send conflict notification to %s", tg_id)


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
    # Check calendar conflicts — every day at 09:00
    scheduler.add_job(
        check_conflicts,
        trigger="cron",
        hour=9,
        minute=0,
        kwargs={"bot": bot},
        id="check_conflicts",
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
