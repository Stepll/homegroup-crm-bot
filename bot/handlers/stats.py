from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client

logger = logging.getLogger(__name__)

router = Router()

PERIODS = {"1m": "1 місяць", "3m": "3 місяці", "6m": "6 місяців"}


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


def _cb(group_id: int, period: str, page: int) -> str:
    return f"st_{group_id}_{period}_{page}"


def _keyboard(group_id: int, period: str, page: int) -> InlineKeyboardMarkup:
    def period_btn(p: str) -> InlineKeyboardButton:
        label = f"· {p} ·" if p == period else p
        return InlineKeyboardButton(text=label, callback_data=_cb(group_id, p, page))

    period_row = [period_btn("1m"), period_btn("3m"), period_btn("6m")]

    if page == 1:
        nav = InlineKeyboardButton(
            text="Активність учасників →",
            callback_data=_cb(group_id, period, 2),
        )
    else:
        nav = InlineKeyboardButton(
            text="← Відвідуваність зустрічей",
            callback_data=_cb(group_id, period, 1),
        )

    return InlineKeyboardMarkup(inline_keyboard=[
        period_row,
        [nav],
        [InlineKeyboardButton(text="← Домашка", callback_data="hg_overview")],
    ])


async def _render(
    bot: Bot, chat_id: int, message_id: int, group_id: int, period: str, page: int
) -> None:
    stats = await api_client.get_group_stats(group_id, period)
    text = _page1_text(stats, period) if page == 1 else _page2_text(stats, period)
    await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=_keyboard(group_id, period, page))


@router.message(Command("stats"))
async def cmd_stats(message: Message, bot: Bot) -> None:
    chat_id = str(message.chat.id)

    groups = await api_client.get_groups()
    group = next((g for g in groups if g.get("telegramGroupId") == chat_id), None)
    if not group:
        await message.answer("Ця група не підключена до CRM.")
        return

    group_id = group["id"]
    period = "3m"
    page = 1
    stats = await api_client.get_group_stats(group_id, period)
    text = _page1_text(stats, period)
    await message.answer(text, reply_markup=_keyboard(group_id, period, page))


@router.callback_query(F.data.startswith("st_"))
async def cb_stats(callback: CallbackQuery, bot: Bot) -> None:
    try:
        parts = callback.data.split("_")
        group_id = int(parts[1])
        period = parts[2]
        page = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Помилка даних.")
        return

    try:
        await _render(bot, callback.message.chat.id, callback.message.message_id, group_id, period, page)
    except Exception as e:
        logger.exception("Stats render failed")
        await callback.answer(f"{type(e).__name__}: {str(e)[:60]}", show_alert=True)
        return

    await callback.answer()
