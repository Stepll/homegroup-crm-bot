import html
import logging
import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client
from bot.utils import find_admin_by_telegram

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

logger = logging.getLogger(__name__)


async def _get_admin_group(message: Message) -> tuple[dict, int] | None:
    username = message.from_user.username if message.from_user else None
    admin = await find_admin_by_telegram(username or "")
    if admin is None:
        await message.answer("Ваш акаунт не знайдено в CRM.")
        return None
    group_id = admin.get("primaryGroupId")
    if not group_id:
        await message.answer("У вас не вказана основна група в CRM.")
        return None
    return admin, group_id


def _need_text(need: dict) -> str:
    subject = html.escape(need.get("subjectName") or "")
    description = html.escape(need.get("description") or "")
    lines = ["<b>Потреба групи</b>", ""]
    if subject:
        lines.append(f"👤 {subject}")
    if description:
        lines.append(description)
    return "\n".join(lines)


def _need_kb(group_id: int, need_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Не актуальна",
                callback_data=f"nd_status_irrelevant_{group_id}_{need_id}",
            ),
            InlineKeyboardButton(
                text="Отримано відповідь",
                callback_data=f"nd_status_answered_{group_id}_{need_id}",
            ),
        ],
    ])


def _need_undo_kb(group_id: int, need_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скасувати", callback_data=f"nd_undo_{group_id}_{need_id}")],
    ])


@router.message(F.text == "Рандомна потреба")
async def btn_random_need(message: Message) -> None:
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result

    try:
        needs = await api_client.get_group_needs(group_id)
    except Exception:
        logger.exception("Failed to fetch needs for group %s", group_id)
        await message.answer("Не вдалося отримати потреби. Спробуйте ще раз.")
        return

    active = [n for n in needs if n.get("status") == "active"]
    if not active:
        await message.answer("Немає активних потреб у вашій домашці.")
        return

    need = random.choice(active)
    await message.answer(
        _need_text(need),
        parse_mode="HTML",
        reply_markup=_need_kb(group_id, need["id"]),
    )


@router.callback_query(F.data.startswith("nd_status_"))
async def cb_need_status(callback: CallbackQuery) -> None:
    # nd_status_{irrelevant|answered}_{group_id}_{need_id}
    parts = callback.data.split("_")
    new_status = parts[2]
    group_id = int(parts[3])
    need_id = int(parts[4])

    try:
        needs = await api_client.get_group_needs(group_id)
        need = next((n for n in needs if n["id"] == need_id), None)
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
        await api_client.update_need(group_id, need_id, payload)
    except Exception:
        logger.exception("Failed to update need %s status", need_id)
        await callback.answer("Помилка оновлення. Спробуйте ще раз.", show_alert=True)
        return

    await callback.message.edit_text(
        _need_text(need) + "\n\n<i>Статус змінено</i>",
        parse_mode="HTML",
        reply_markup=_need_undo_kb(group_id, need_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("nd_undo_"))
async def cb_need_undo(callback: CallbackQuery) -> None:
    # nd_undo_{group_id}_{need_id}
    parts = callback.data.split("_")
    group_id = int(parts[2])
    need_id = int(parts[3])

    try:
        needs = await api_client.get_group_needs(group_id)
        need = next((n for n in needs if n["id"] == need_id), None)
        if need is None:
            await callback.answer("Потребу не знайдено.", show_alert=True)
            return

        payload = {
            "subjectName": need["subjectName"],
            "description": need["description"],
            "status": "active",
            "personId": need.get("personId"),
            "userId": need.get("userId"),
        }
        await api_client.update_need(group_id, need_id, payload)
    except Exception:
        logger.exception("Failed to revert need %s status", need_id)
        await callback.answer("Помилка скасування. Спробуйте ще раз.", show_alert=True)
        return

    await callback.message.edit_text(
        _need_text(need),
        parse_mode="HTML",
        reply_markup=_need_kb(group_id, need_id),
    )
    await callback.answer()
