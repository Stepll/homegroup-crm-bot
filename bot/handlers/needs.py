import html
import logging
import random

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client
from bot.utils import find_admin_by_telegram, find_person_by_telegram

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

logger = logging.getLogger(__name__)


class AddNeedStates(StatesGroup):
    waiting_guest_name = State()
    waiting_need_text = State()


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
    username = message.from_user.username if message.from_user else None
    if not username:
        await message.answer("У вас не встановлений @username у Telegram.")
        return

    admin = await find_admin_by_telegram(username)
    is_admin = admin is not None
    if is_admin:
        group_id = admin.get("primaryGroupId")
    else:
        person = await find_person_by_telegram(username)
        if person is None:
            await message.answer("Ваш акаунт не знайдено в CRM.")
            return
        group_id = person.get("primaryGroupId")

    if not group_id:
        await message.answer("У вас не вказана основна група в CRM.")
        return

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
        reply_markup=_need_kb(group_id, need["id"]) if is_admin else None,
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


# ── Add need flow ─────────────────────────────────────────────────────────────

_ADD_NEED_PROMPT = "<b>Створити потребу для:</b>"


def _add_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Член домашки", callback_data="addn_type_member"),
            InlineKeyboardButton(text="Гість", callback_data="addn_type_guest"),
        ],
    ])


def _add_back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Назад", callback_data="addn_back_start")],
    ])


def _add_back_to_picker_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Назад", callback_data="addn_back_picker")],
    ])


def _member_picker_kb(members: list) -> InlineKeyboardMarkup:
    sorted_members = sorted(
        members,
        key=lambda m: f"{(m.get('name') or '').lower()} {(m.get('lastName') or '').lower()}",
    )
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for m in sorted_members:
        is_admin = m.get("isAdmin", False)
        member_id = m.get("userId") if is_admin else m.get("id")
        if member_id is None:
            continue
        full = f"{m.get('name') or ''} {m.get('lastName') or ''}".strip() or "—"
        tc = "u" if is_admin else "p"
        row.append(InlineKeyboardButton(text=full, callback_data=f"addn_mem_{tc}_{member_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="addn_back_start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "Додати потребу")
async def btn_add_need(message: Message, state: FSMContext) -> None:
    await state.clear()
    username = message.from_user.username if message.from_user else None
    if not username:
        await message.answer("У вас не встановлений @username у Telegram.")
        return

    # Admin → picker flow (member/guest)
    admin = await find_admin_by_telegram(username)
    if admin is not None:
        group_id = admin.get("primaryGroupId")
        if not group_id:
            await message.answer("У вас не вказана основна група в CRM.")
            return
        sent = await message.answer(
            _ADD_NEED_PROMPT,
            parse_mode="HTML",
            reply_markup=_add_start_kb(),
        )
        await state.update_data(group_id=group_id, msg_id=sent.message_id)
        return

    # Member → straight to text input, subject = self
    person = await find_person_by_telegram(username)
    if person is None:
        await message.answer("Ваш акаунт не знайдено в CRM.")
        return
    group_id = person.get("primaryGroupId")
    if not group_id:
        await message.answer("У вас не вказана основна група в CRM.")
        return

    full_name = f"{person.get('name') or ''} {person.get('lastName') or ''}".strip() or "—"
    sent = await message.answer("<b>Введіть текст вашої потреби:</b>", parse_mode="HTML")
    await state.set_state(AddNeedStates.waiting_need_text)
    await state.update_data(
        group_id=group_id,
        msg_id=sent.message_id,
        member_type="self",
        subject_name=full_name,
        person_id=person["id"],
        user_id=None,
    )


@router.callback_query(F.data == "addn_back_start")
async def cb_add_back_start(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_id")
    msg_id = data.get("msg_id")
    await state.clear()
    if group_id and msg_id:
        await state.update_data(group_id=group_id, msg_id=msg_id)
    await callback.message.edit_text(
        _ADD_NEED_PROMPT,
        parse_mode="HTML",
        reply_markup=_add_start_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "addn_type_member")
async def cb_add_type_member(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_id")
    if not group_id:
        await callback.answer("Сесію втрачено. Натисніть «Додати потребу» знову.", show_alert=True)
        return

    try:
        members = await api_client.get_group_members(group_id)
    except Exception:
        logger.exception("Failed to fetch members for group %s", group_id)
        await callback.answer("Не вдалося отримати список членів.", show_alert=True)
        return

    if not members:
        await callback.answer("У домашці немає членів.", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>Оберіть члена домашки:</b>",
        parse_mode="HTML",
        reply_markup=_member_picker_kb(members),
    )
    await callback.answer()


@router.callback_query(F.data == "addn_type_guest")
async def cb_add_type_guest(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_id")
    if not group_id:
        await callback.answer("Сесію втрачено. Натисніть «Додати потребу» знову.", show_alert=True)
        return

    await state.set_state(AddNeedStates.waiting_guest_name)
    await state.update_data(group_id=group_id, msg_id=callback.message.message_id, member_type="guest")
    await callback.message.edit_text(
        "<b>Введіть імʼя гостя:</b>",
        parse_mode="HTML",
        reply_markup=_add_back_to_start_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("addn_mem_"))
async def cb_add_member_picked(callback: CallbackQuery, state: FSMContext) -> None:
    # addn_mem_{p|u}_{id}
    parts = callback.data.split("_")
    tc = parts[2]
    member_id = int(parts[3])
    data = await state.get_data()
    group_id = data.get("group_id")
    if not group_id:
        await callback.answer("Сесію втрачено.", show_alert=True)
        return

    try:
        if tc == "u":
            member = await api_client.get_admin(member_id)
        else:
            member = await api_client.get_person(member_id)
    except Exception:
        logger.exception("Failed to fetch member %s/%s", tc, member_id)
        await callback.answer("Не вдалося отримати дані.", show_alert=True)
        return

    name = f"{member.get('name') or ''} {member.get('lastName') or ''}".strip() or "—"

    await state.set_state(AddNeedStates.waiting_need_text)
    await state.update_data(
        group_id=group_id,
        msg_id=callback.message.message_id,
        member_type="member",
        subject_name=name,
        person_id=None if tc == "u" else member_id,
        user_id=member_id if tc == "u" else None,
    )
    await callback.message.edit_text(
        f"<b>Введіть текст потреби для {html.escape(name)}:</b>",
        parse_mode="HTML",
        reply_markup=_add_back_to_picker_kb(),
    )
    await callback.answer()


@router.message(AddNeedStates.waiting_guest_name)
async def receive_guest_name(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    msg_id = data.get("msg_id")
    group_id = data.get("group_id")
    chat_id = message.chat.id

    try:
        await bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass

    name = (message.text or "").strip()
    if not name:
        return

    await state.set_state(AddNeedStates.waiting_need_text)
    await state.update_data(
        group_id=group_id,
        msg_id=msg_id,
        member_type="guest",
        subject_name=name,
        person_id=None,
        user_id=None,
    )
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=f"<b>Введіть текст потреби для {html.escape(name)}:</b>",
        parse_mode="HTML",
        reply_markup=_add_back_to_picker_kb(),
    )


@router.callback_query(F.data == "addn_back_picker")
async def cb_add_back_picker(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_id")
    msg_id = data.get("msg_id")
    member_type = data.get("member_type")

    if not group_id:
        await callback.answer("Сесію втрачено.", show_alert=True)
        return

    if member_type == "guest":
        await state.set_state(AddNeedStates.waiting_guest_name)
        await state.update_data(group_id=group_id, msg_id=msg_id, member_type="guest")
        await callback.message.edit_text(
            "<b>Введіть імʼя гостя:</b>",
            parse_mode="HTML",
            reply_markup=_add_back_to_start_kb(),
        )
    else:
        try:
            members = await api_client.get_group_members(group_id)
        except Exception:
            logger.exception("Failed to fetch members for group %s", group_id)
            await callback.answer("Не вдалося отримати список членів.", show_alert=True)
            return
        await state.set_state(state=None)
        await state.update_data(group_id=group_id, msg_id=msg_id)
        await callback.message.edit_text(
            "<b>Оберіть члена домашки:</b>",
            parse_mode="HTML",
            reply_markup=_member_picker_kb(members),
        )
    await callback.answer()


@router.message(AddNeedStates.waiting_need_text)
async def receive_need_text(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    msg_id = data.get("msg_id")
    group_id = data.get("group_id")
    subject_name = data.get("subject_name") or ""
    person_id = data.get("person_id")
    user_id = data.get("user_id")
    member_type = data.get("member_type")
    chat_id = message.chat.id

    try:
        await bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass

    text = (message.text or "").strip()
    if not text:
        return

    try:
        await api_client.create_need(group_id, {
            "subjectName": subject_name,
            "description": text,
            "personId": person_id,
            "userId": user_id,
        })
    except Exception:
        logger.exception("Failed to create need")
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text="Помилка збереження. Спробуйте ще раз.",
        )
        await state.clear()
        return

    suffix = " (гість)" if member_type == "guest" else ""
    final_text = (
        "<b>✅ Потребу додано</b>\n\n"
        f"👤 {html.escape(subject_name)}{suffix}\n"
        f"{html.escape(text)}"
    )
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=final_text,
        parse_mode="HTML",
    )
    await state.clear()
