from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from bot.api_client import api_client
from bot import notif_settings as ns

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

# Persistent conflict state — loaded from disk on startup
# key: "{group_id}:{meeting_date}", value: "conflicted" | "resolved"
_CONFLICT_STATE_FILE = os.path.join(os.path.dirname(__file__), "../../data/conflict_state.json")
_conflict_state: dict[str, str] = {}


def _load_conflict_state() -> None:
    global _conflict_state
    try:
        with open(_CONFLICT_STATE_FILE) as f:
            _conflict_state = json.load(f)
        logger.info("Loaded conflict state: %d entries", len(_conflict_state))
    except FileNotFoundError:
        _conflict_state = {}
    except Exception:
        logger.exception("Failed to load conflict state, starting fresh")
        _conflict_state = {}


def _save_conflict_state() -> None:
    try:
        os.makedirs(os.path.dirname(_CONFLICT_STATE_FILE), exist_ok=True)
        with open(_CONFLICT_STATE_FILE, "w") as f:
            json.dump(_conflict_state, f)
    except Exception:
        logger.exception("Failed to save conflict state")


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

        try:
            settings = await ns.get(group_id)
            if not settings.get("attendance_ask", True):
                continue
        except Exception:
            pass

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

        try:
            notif = await ns.get(group["id"])
        except Exception:
            notif = ns.DEFAULTS

        today_events = [e["name"] for e in events if _event_matches(e, today)] if notif.get("event_day", True) else []
        week_events = [e["name"] for e in events if _event_matches(e, in_7)] if notif.get("event_7days", True) else []

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
        has_conflict = bool(conflicts)
        key = f"{group['id']}:{meeting_date}"
        current_state = _conflict_state.get(key)

        try:
            notif = await ns.get(group["id"])
        except Exception:
            notif = ns.DEFAULTS

        try:
            if has_conflict and notif.get("conflict", True) and (current_state != "conflicted" or force):
                names = ", ".join(c.get("title", "?") for c in conflicts)
                await bot.send_message(
                    int(tg_id),
                    f"⚠️ Накладка в розкладі — домашка перетинається з: {names}",
                )
                _conflict_state[key] = "conflicted"
                _save_conflict_state()

            elif not has_conflict and notif.get("conflict_resolved", True) and current_state == "conflicted":
                await bot.send_message(
                    int(tg_id),
                    "✅ Все чисто — домашка більше ні з чим не перетинається",
                )
                _conflict_state[key] = "resolved"
                _save_conflict_state()

        except Exception:
            logger.exception("Failed to send conflict notification to %s", tg_id)


async def notify_meeting_plan(bot: Bot) -> None:
    # TODO: send plan day before meeting
    logger.info("notify_meeting_plan triggered")


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    _load_conflict_state()
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
