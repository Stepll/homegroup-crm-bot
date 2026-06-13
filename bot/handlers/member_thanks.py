"""Member: "Подякувати за молитву" flow.

Shows the member's own active needs; clicking one expands to a card with
status-change buttons (Отримано відповідь / Не актуальна / ← Назад).
"""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client
from bot.utils import find_person_by_telegram

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

logger = logging.getLogger(__name__)


async def _get_person_group(message_or_cb) -> tuple[dict, int] | None:
    username = (message_or_cb.from_user.username if message_or_cb.from_user else None) or ""
    person = await find_person_by_telegram(username)
    if person is None:
        if isinstance(message_or_cb, Message):
            await message_or_cb.answer("Ваш акаунт не знайдено в CRM.")
        else:
            await message_or_cb.answer("Ваш акаунт не знайдено в CRM.", show_alert=True)
        return None
    group_id = person.get("primaryGroupId")
    if not group_id:
        if isinstance(message_or_cb, Message):
            await message_or_cb.answer("У вас не вказана основна група в CRM.")
        else:
            await message_or_cb.answer("У вас не вказана основна група в CRM.", show_alert=True)
        return None
    return person, group_id


def _truncate(s: str, n: int = 40) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


async def _own_active_needs(person_id: int, group_id: int) -> list[dict]:
    needs = await api_client.get_group_needs(group_id)
    return [n for n in needs if n.get("status") == "active" and n.get("personId") == person_id]


def _list_kb(needs: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_truncate(n.get("description") or "—"),
                              callback_data=f"th_open_{n['id']}")]
        for n in needs
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _card_kb(need_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Отримано відповідь",
                                 callback_data=f"th_set_answered_{need_id}"),
            InlineKeyboardButton(text="Не актуальна",
                                 callback_data=f"th_set_irrelevant_{need_id}"),
        ],
        [InlineKeyboardButton(text="← Назад", callback_data="th_back")],
    ])


def _list_text(needs: list[dict]) -> str:
    if not needs:
        return "<b>У вас немає активних потреб.</b>"
    return "<b>Ваші активні потреби:</b>\n\nОберіть потребу щоб змінити статус:"


def _card_text(need: dict) -> str:
    return (
        "<b>Потреба:</b>\n\n"
        f"{html.escape(need.get('description') or '—')}"
    )


@router.message(F.text == "Подякувати за молитву")
async def btn_thanks(message: Message) -> None:
    result = await _get_person_group(message)
    if result is None:
        return
    person, group_id = result

    try:
        needs = await _own_active_needs(person["id"], group_id)
    except Exception:
        logger.exception("Failed to fetch own needs for person %s", person["id"])
        await message.answer("Не вдалося отримати потреби. Спробуйте ще раз.")
        return

    if not needs:
        await message.answer("У вас немає активних потреб.")
        return

    await message.answer(
        _list_text(needs), parse_mode="HTML", reply_markup=_list_kb(needs),
    )


@router.callback_query(F.data == "th_back")
async def cb_back(callback: CallbackQuery) -> None:
    result = await _get_person_group(callback)
    if result is None:
        return
    person, group_id = result

    needs = await _own_active_needs(person["id"], group_id)
    if not needs:
        await callback.message.edit_text("У вас більше немає активних потреб.")
        await callback.answer()
        return

    await callback.message.edit_text(
        _list_text(needs), parse_mode="HTML", reply_markup=_list_kb(needs),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("th_open_"))
async def cb_open(callback: CallbackQuery) -> None:
    need_id = int(callback.data.split("_", 2)[2])
    result = await _get_person_group(callback)
    if result is None:
        return
    person, group_id = result

    needs = await _own_active_needs(person["id"], group_id)
    need = next((n for n in needs if n["id"] == need_id), None)
    if need is None:
        await callback.answer("Потребу не знайдено.", show_alert=True)
        return

    await callback.message.edit_text(
        _card_text(need), parse_mode="HTML", reply_markup=_card_kb(need_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("th_set_"))
async def cb_set_status(callback: CallbackQuery) -> None:
    # th_set_{answered|irrelevant}_{need_id}
    parts = callback.data.split("_")
    new_status = parts[2]
    need_id = int(parts[3])
    if new_status not in ("answered", "irrelevant"):
        await callback.answer()
        return

    result = await _get_person_group(callback)
    if result is None:
        return
    person, group_id = result

    needs = await api_client.get_group_needs(group_id)
    need = next((n for n in needs if n["id"] == need_id and n.get("personId") == person["id"]), None)
    if need is None:
        await callback.answer("Потребу не знайдено.", show_alert=True)
        return

    payload = {
        "subjectName": need["subjectName"],
        "description": need["description"],
        "status": new_status,
        "personId": need.get("personId"),
        "userId": need.get("userId"),
    }
    try:
        await api_client.update_need(group_id, need_id, payload)
    except Exception:
        logger.exception("Failed to update need %s status", need_id)
        await callback.answer("Помилка оновлення. Спробуйте ще раз.", show_alert=True)
        return

    remaining = [n for n in needs if n.get("status") == "active"
                 and n.get("personId") == person["id"] and n["id"] != need_id]
    if not remaining:
        toast = "Дякую! Статус оновлено." if new_status == "answered" else "Статус оновлено."
        await callback.message.edit_text(
            "У вас більше немає активних потреб.\n\n<i>Слава Богу!</i>" if new_status == "answered"
            else "У вас більше немає активних потреб.",
            parse_mode="HTML",
        )
        await callback.answer(toast)
        return

    await callback.message.edit_text(
        _list_text(remaining), parse_mode="HTML", reply_markup=_list_kb(remaining),
    )
    await callback.answer("Статус оновлено")
