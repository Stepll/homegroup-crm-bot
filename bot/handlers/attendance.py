from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.api_client import api_client

router = Router()
logger = logging.getLogger(__name__)


# ── Session state ─────────────────────────────────────────────────────────────

@dataclass
class AttendanceMember:
    display_name: str
    person_id: int | None
    user_id: int | None
    is_present: bool = False


@dataclass
class AttendanceSession:
    group_id: int
    meeting_date: str
    members: list[AttendanceMember]
    message_id: int
    state: str = "init"  # init | date_pick | members | guests
    past_dates: list[str] = field(default_factory=list)


# keyed by chat_id
sessions: dict[int, AttendanceSession] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_date(date: str) -> str:
    try:
        y, m, d = date.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return date


_UKR_DAYS: dict[str, int] = {
    "Неділя": 6, "Понеділок": 0, "Вівторок": 1, "Середа": 2,
    "Четвер": 3, "Пʼятниця": 4, "П'ятниця": 4, "Субота": 5,
}


def _generate_past_dates(meeting_day: str | None, before_date: str, count: int) -> list[str]:
    try:
        anchor = date.fromisoformat(before_date)
    except Exception:
        return []
    results = []
    if meeting_day and meeting_day in _UKR_DAYS:
        target_weekday = _UKR_DAYS[meeting_day]
        # Go back week by week from before_date
        d = anchor - timedelta(days=1)
        while d.weekday() != target_weekday:
            d -= timedelta(days=1)
        for _ in range(count):
            results.append(d.isoformat())
            d -= timedelta(weeks=1)
    else:
        for i in range(1, count + 1):
            results.append((anchor - timedelta(weeks=i)).isoformat())
    return results


def _build_members(raw_members: list) -> list[AttendanceMember]:
    members = []
    for m in raw_members:
        if m.get("isFormer"):
            continue
        name = m.get("name", "")
        last = m.get("lastName") or ""
        display = f"{name} {last}".strip()
        person_id = None if m.get("isAdmin") else m["id"]
        user_id = m.get("userId") if m.get("isAdmin") else None
        members.append(AttendanceMember(display_name=display, person_id=person_id, user_id=user_id))
    return members


def _apply_existing_attendance(members: list[AttendanceMember], records: list) -> None:
    present_person_ids = {r["personId"] for r in records if r.get("wasPresent") and r.get("personId")}
    present_user_ids = {r["userId"] for r in records if r.get("wasPresent") and r.get("userId")}
    for m in members:
        if m.person_id is not None and m.person_id in present_person_ids:
            m.is_present = True
        elif m.user_id is not None and m.user_id in present_user_ids:
            m.is_present = True


async def _load_members_for_date(group_id: int, date: str) -> list[AttendanceMember]:
    raw_members = await api_client.get_group_members(group_id)
    members = _build_members(raw_members)
    try:
        records = await api_client.get_attendance(group_id, date)
        _apply_existing_attendance(members, records)
    except Exception:
        logger.warning("Could not load existing attendance for group %s date %s", group_id, date)
    return members


def _members_text(session: AttendanceSession) -> str:
    count = sum(1 for m in session.members if m.is_present)
    return (
        f"Відмітьте присутніх за {_format_date(session.meeting_date)}:\n"
        f"Відмічено: {count} / {len(session.members)}"
    )


def _summary_text(session: AttendanceSession, guest_count: int) -> str:
    present = [m for m in session.members if m.is_present]
    lines = [
        f"✅ Відмітка за {_format_date(session.meeting_date)} збережена",
        "",
        f"Присутніх: {len(present)}",
    ]
    for m in present:
        lines.append(f"  • {m.display_name}")
    if guest_count > 0:
        lines.append(f"\nГостей: {guest_count}")
    lines.append(f"\nВсього на домашці: {len(present) + guest_count}")
    return "\n".join(lines)


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _initial_keyboard(meeting_date: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Відмітити за {_format_date(meeting_date)}",
            callback_data="att_date_today",
        )],
        [InlineKeyboardButton(text="📅 Відмітити за минулу дату", callback_data="att_date_pick")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="att_cancel")],
    ])


def _date_pick_keyboard(past_dates: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=_format_date(d), callback_data=f"att_pastdate_{d}")]
        for d in past_dates
    ]
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="att_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _members_keyboard(members: list[AttendanceMember]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{'✅' if m.is_present else '◻️'} {m.display_name}",
            callback_data=f"att_toggle_{i}",
        )]
        for i, m in enumerate(members)
    ]
    buttons.append([
        InlineKeyboardButton(text="Готово ✓", callback_data="att_done"),
        InlineKeyboardButton(text="❌ Скасувати", callback_data="att_cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _guests_keyboard() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"att_guests_{i}") for i in range(6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"att_guests_{i}") for i in range(6, 11)]
    cancel_row = [InlineKeyboardButton(text="❌ Скасувати", callback_data="att_cancel")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, cancel_row])


# ── Entry point (used by command + scheduler) ─────────────────────────────────

async def start_attendance_flow(
    bot: Bot, group_id: int, telegram_group_id: str, meeting_date: str
) -> None:
    chat_id = int(telegram_group_id)

    raw_members = await api_client.get_group_members(group_id)
    members = _build_members(raw_members)

    msg = await bot.send_message(
        chat_id,
        f"Відмітка присутніх за {_format_date(meeting_date)}",
        reply_markup=_initial_keyboard(meeting_date),
    )
    sessions[chat_id] = AttendanceSession(
        group_id=group_id,
        meeting_date=meeting_date,
        members=members,
        message_id=msg.message_id,
    )


# ── Command handler ───────────────────────────────────────────────────────────

@router.message(Command("attendance"))
async def cmd_attendance(message: Message, bot: Bot) -> None:
    chat_id = str(message.chat.id)

    groups = await api_client.get_groups()
    group = next((g for g in groups if g.get("telegramGroupId") == chat_id), None)
    if not group:
        await message.answer("Ця група не підключена до CRM.")
        return

    cabinet = await api_client.get_cabinet(group["id"])
    # Prefer the most recent SCHEDULED meeting (computed from meetingDay + override),
    # fallback to last meeting with attendance records.
    # Otherwise, if a recent meeting happened but nothing was marked yet,
    # the bot would suggest a date from weeks ago.
    meeting_date = cabinet.get("prevScheduledMeetingDate") or cabinet.get("lastMeetingDate")
    if not meeting_date:
        await message.answer("Немає дати зустрічі.")
        return

    await start_attendance_flow(bot, group["id"], chat_id, meeting_date)


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "att_cancel")
async def cb_cancel(callback: CallbackQuery) -> None:
    sessions.pop(callback.message.chat.id, None)
    await callback.message.delete()
    await callback.answer()


# ── Date selection ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "att_date_today")
async def cb_date_today(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    session = sessions.get(chat_id)
    if not session:
        await callback.answer("Сесія застаріла, запустіть /attendance знову.")
        return

    try:
        records = await api_client.get_attendance(session.group_id, session.meeting_date)
        _apply_existing_attendance(session.members, records)
    except Exception:
        logger.warning("Could not load existing attendance for group %s", session.group_id)

    session.state = "members"
    await callback.message.edit_text(
        _members_text(session),
        reply_markup=_members_keyboard(session.members),
    )
    await callback.answer()


@router.callback_query(F.data == "att_date_pick")
async def cb_date_pick(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    session = sessions.get(chat_id)
    if not session:
        await callback.answer("Сесія застаріла, запустіть /attendance знову.")
        return

    past_dates: list[str] = []
    try:
        summary = await api_client.get_attendance_summary(session.group_id)
        logger.info("Summary for group %s: %s", session.group_id, summary)
        past_dates = sorted(
            [s["meetingDate"] for s in summary if s["meetingDate"] < session.meeting_date],
            reverse=True,
        )[:4]
    except Exception:
        logger.exception("Failed to load attendance summary for group %s", session.group_id)

    # Fallback: generate dates from meeting schedule if summary gave nothing
    if not past_dates:
        try:
            group = await api_client.get_group(session.group_id)
            meeting_day = group.get("meetingDay")
            past_dates = _generate_past_dates(meeting_day, session.meeting_date, 4)
        except Exception:
            logger.exception("Failed to generate past dates for group %s", session.group_id)

    if not past_dates:
        await callback.answer("Немає минулих зустрічей.", show_alert=True)
        return

    session.state = "date_pick"
    session.past_dates = past_dates
    await callback.message.edit_text(
        "Оберіть дату:",
        reply_markup=_date_pick_keyboard(past_dates),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("att_pastdate_"))
async def cb_past_date(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    session = sessions.get(chat_id)
    if not session or session.state != "date_pick":
        await callback.answer()
        return

    date = callback.data[len("att_pastdate_"):]
    session.meeting_date = date
    session.members = await _load_members_for_date(session.group_id, date)
    session.state = "members"

    await callback.message.edit_text(
        _members_text(session),
        reply_markup=_members_keyboard(session.members),
    )
    await callback.answer()


# ── Member toggling ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("att_toggle_"))
async def cb_toggle(callback: CallbackQuery) -> None:
    session = sessions.get(callback.message.chat.id)
    if not session or session.state != "members":
        await callback.answer()
        return
    index = int(callback.data.split("_")[2])
    session.members[index].is_present = not session.members[index].is_present
    await callback.message.edit_text(
        _members_text(session),
        reply_markup=_members_keyboard(session.members),
    )
    await callback.answer()


@router.callback_query(F.data == "att_done")
async def cb_done(callback: CallbackQuery) -> None:
    session = sessions.get(callback.message.chat.id)
    if not session or session.state != "members":
        await callback.answer()
        return
    session.state = "guests"
    await callback.message.edit_text(
        "Скільки гостей на домашці?",
        reply_markup=_guests_keyboard(),
    )
    await callback.answer()


# ── Guest count + save ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("att_guests_"))
async def cb_guests(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    session = sessions.pop(chat_id, None)
    if not session or session.state != "guests":
        await callback.answer()
        return

    guest_count = int(callback.data.split("_")[2])

    entries = []
    for m in session.members:
        entry: dict = {"wasPresent": m.is_present}
        if m.person_id is not None:
            entry["personId"] = m.person_id
        else:
            entry["userId"] = m.user_id
        entries.append(entry)

    try:
        await api_client.record_attendance(session.group_id, session.meeting_date, entries)
        await api_client.save_attendance_meta(session.group_id, session.meeting_date, guest_count)
        await callback.message.edit_text(_summary_text(session, guest_count))
    except Exception:
        logger.exception("Failed to save attendance for group %s", session.group_id)
        await callback.message.edit_text("❌ Помилка збереження. Спробуйте ще раз /attendance")

    await callback.answer()
