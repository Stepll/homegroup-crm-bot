from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client

router = Router()

PERIODS = {"1m": "1 місяць", "3m": "3 місяці", "6m": "6 місяців"}


# ── Session ───────────────────────────────────────────────────────────────────

@dataclass
class StatsSession:
    group_id: int
    period: str = "3m"
    page: int = 1


stats_sessions: dict[int, StatsSession] = {}


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    try:
        _, m, d = iso.split("-")
        return f"{d}.{m}"
    except Exception:
        return iso


def _page1_text(stats: dict, period: str) -> str:
    label = PERIODS[period]
    meetings = stats.get("meetings") or []
    lines = [f"📊 Відвідуваність за {label}", ""]
    if not meetings:
        lines.append("Зустрічей за цей період не знайдено.")
    for m in sorted(meetings, key=lambda x: x["date"]):
        total = m["presentCount"] + m.get("guestCount", 0)
        line = f"{_fmt_date(m['date'])} — {total} осіб"
        if m.get("guestCount"):
            line += f" (вкл. {m['guestCount']} гостей)"
        lines.append(line)
    return "\n".join(lines)


def _page2_text(stats: dict, period: str) -> str:
    label = PERIODS[period]
    persons = stats.get("personStats") or []
    lines = [f"👥 Активність учасників за {label}", ""]
    if not persons:
        lines.append("Даних про учасників немає.")
    for p in persons:
        present = p["presentCount"]
        total = p["totalMeetings"]
        absent = total - present
        line = f"{p['fullName']}: {present} з {total} зустрічей"
        if absent > 4:
            line += f" (не було {absent} останніх разів ⚠️)"
        lines.append(line)
    return "\n".join(lines)


def _keyboard(session: StatsSession) -> InlineKeyboardMarkup:
    def period_btn(p: str) -> InlineKeyboardButton:
        label = f"· {p} ·" if p == session.period else p
        return InlineKeyboardButton(text=label, callback_data=f"stats_period_{p}")

    period_row = [period_btn("1m"), period_btn("3m"), period_btn("6m")]

    if session.page == 1:
        nav = InlineKeyboardButton(text="Активність учасників →", callback_data="stats_page_2")
    else:
        nav = InlineKeyboardButton(text="← Відвідуваність зустрічей", callback_data="stats_page_1")

    return InlineKeyboardMarkup(inline_keyboard=[period_row, [nav]])


# ── Render ────────────────────────────────────────────────────────────────────

async def _render(bot: Bot, chat_id: int, message_id: int, session: StatsSession) -> None:
    stats = await api_client.get_group_stats(session.group_id, session.period)
    text = _page1_text(stats, session.period) if session.page == 1 else _page2_text(stats, session.period)
    await bot.edit_message_text(text, chat_id, message_id, reply_markup=_keyboard(session))


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message, bot: Bot) -> None:
    chat_id = str(message.chat.id)

    groups = await api_client.get_groups()
    group = next((g for g in groups if g.get("telegramGroupId") == chat_id), None)
    if not group:
        await message.answer("Ця група не підключена до CRM.")
        return

    session = StatsSession(group_id=group["id"])
    stats = await api_client.get_group_stats(session.group_id, session.period)
    text = _page1_text(stats, session.period)

    msg = await message.answer(text, reply_markup=_keyboard(session))
    session_with_id = StatsSession(group_id=group["id"])
    stats_sessions[message.chat.id] = session_with_id
    stats_sessions[message.chat.id].__dict__["_msg_id"] = msg.message_id


@router.callback_query(F.data.startswith("stats_period_"))
async def cb_period(callback: CallbackQuery, bot: Bot) -> None:
    chat_id = callback.message.chat.id
    session = stats_sessions.get(chat_id)
    if not session:
        await callback.answer("Запустіть /stats знову.")
        return
    session.period = callback.data.split("_")[2]
    await _render(bot, chat_id, callback.message.message_id, session)
    await callback.answer()


@router.callback_query(F.data.startswith("stats_page_"))
async def cb_page(callback: CallbackQuery, bot: Bot) -> None:
    chat_id = callback.message.chat.id
    session = stats_sessions.get(chat_id)
    if not session:
        await callback.answer("Запустіть /stats знову.")
        return
    session.page = int(callback.data.split("_")[2])
    await _render(bot, chat_id, callback.message.message_id, session)
    await callback.answer()
