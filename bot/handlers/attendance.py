from __future__ import annotations

import logging
from dataclasses import dataclass, field

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

SEPARATOR = "------------------"


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
    state: str = "init"  # init | members | guests
    selected_names: list[str] = field(default_factory=list)


# keyed by chat_id
sessions: dict[int, AttendanceSession] = {}


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _members_keyboard(members: list[AttendanceMember]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{'✅' if m.is_present else '◻️'} {m.display_name}",
            callback_data=f"att_toggle_{i}",
        )]
        for i, m in enumerate(members)
    ]
    buttons.append([InlineKeyboardButton(text="Готово ✓", callback_data="att_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _guests_keyboard() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"att_guests_{i}") for i in range(6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"att_guests_{i}") for i in range(6, 11)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_date(date: str) -> str:
    try:
        y, m, d = date.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return date


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


# ── Shared entry point (used by command + scheduler) ──────────────────────────

async def start_attendance_flow(
    bot: Bot, group_id: int, telegram_group_id: str, meeting_date: str
) -> None:
    raw_members = await api_client.get_group_members(group_id)
    members = []
    for m in raw_members:
        name = m.get("name", "")
        last = m.get("lastName") or ""
        display = f"{name} {last}".strip()
        person_id = None if m.get("isAdmin") else m["id"]
        user_id = m.get("userId") if m.get("isAdmin") else None
        members.append(AttendanceMember(display_name=display, person_id=person_id, user_id=user_id))

    chat_id = int(telegram_group_id)
    msg = await bot.send_message(
        chat_id,
        f"Відмітка присутніх за {_format_date(meeting_date)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Відмітити присутніх", callback_data="att_start"),
        ]]),
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
    meeting_date = cabinet.get("lastMeetingDate") or cabinet.get("prevScheduledMeetingDate")
    if not meeting_date:
        await message.answer("Немає дати зустрічі.")
        return

    await start_attendance_flow(bot, group["id"], chat_id, meeting_date)


# ── Callback handlers ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "att_start")
async def cb_start(callback: CallbackQuery) -> None:
    session = sessions.get(callback.message.chat.id)
    if not session:
        await callback.answer("Сесія застаріла, запустіть /attendance знову.")
        return
    session.state = "members"
    await callback.message.edit_text(
        _members_text(session),
        reply_markup=_members_keyboard(session.members),
    )
    await callback.answer()


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
