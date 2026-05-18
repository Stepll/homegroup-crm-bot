import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.api_client import api_client
from bot.utils import find_admin_by_telegram

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

logger = logging.getLogger(__name__)

MONTHS = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня",
    5: "травня", 6: "червня", 7: "липня", 8: "серпня",
    9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
}


class GEStates(StatesGroup):
    create_name = State()
    create_date = State()
    edit_name = State()
    edit_date = State()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_event_date(month: int, day: int, year: int | None) -> str:
    base = f"{day} {MONTHS.get(month, str(month))}"
    return f"{base} {year}" if year else base


def _fmt_days(days: int) -> str:
    if days == 0:
        return "сьогодні!"
    if days == 1:
        return "завтра"
    return f"за {days} дн."


def _events_text(events: list, title: str) -> str:
    lines = [f"<b>{title}</b>", ""]
    if not events:
        lines.append("Немає запланованих подій.")
    else:
        for ev in events:
            date_str = _fmt_event_date(ev["month"], ev["day"], ev.get("year"))
            days_str = _fmt_days(ev["daysUntil"])
            lines.append(f"🔹 {html.escape(ev['name'])} — {date_str} ({days_str})")
    return "\n".join(lines)


def _event_card_text(ev: dict) -> str:
    date_str = _fmt_event_date(ev["month"], ev["day"], ev.get("year"))
    days_str = _fmt_days(ev["daysUntil"])
    return f"<b>{html.escape(ev['name'])}</b>\n\nДата: {date_str}\nЗалишилось: {days_str}"


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


async def _get_group_cb(callback: CallbackQuery) -> int | None:
    username = callback.from_user.username or ""
    admin = await find_admin_by_telegram(username)
    if admin is None:
        await callback.answer("Ваш акаунт не знайдено в CRM.")
        return None
    group_id = admin.get("primaryGroupId")
    if not group_id:
        await callback.answer("У вас не вказана основна група в CRM.")
        return None
    return group_id


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _main_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Показати повний список", callback_data=f"ge_full_{group_id}")],
        [
            InlineKeyboardButton(text="Створити", callback_data=f"ge_create_{group_id}"),
            InlineKeyboardButton(text="Редагувати", callback_data=f"ge_elist_{group_id}"),
        ],
    ])


def _full_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Назад", callback_data=f"ge_main_{group_id}")],
    ])


def _elist_kb(events: list, group_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{ev['name']} — {_fmt_event_date(ev['month'], ev['day'], ev.get('year'))}",
            callback_data=f"ge_ev_{group_id}_{ev['id']}",
        )]
        for ev in events
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"ge_main_{group_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _event_kb(group_id: int, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Змінити назву", callback_data=f"ge_ename_{group_id}_{event_id}"),
            InlineKeyboardButton(text="Змінити дату", callback_data=f"ge_edate_{group_id}_{event_id}"),
        ],
        [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"ge_del_{group_id}_{event_id}")],
        [InlineKeyboardButton(text="← Назад", callback_data=f"ge_elist_{group_id}")],
    ])


def _del_confirm_kb(group_id: int, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так, видалити", callback_data=f"ge_delok_{group_id}_{event_id}"),
            InlineKeyboardButton(text="Скасувати", callback_data=f"ge_ev_{group_id}_{event_id}"),
        ],
    ])


def _cancel_kb(back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скасувати", callback_data=back_cb)],
    ])


# ── Entry point ───────────────────────────────────────────────────────────────

@router.message(F.text == "Події домашки")
async def btn_group_events(message: Message, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result
    events = await api_client.get_group_events(group_id)
    preview = events[:5]
    text = _events_text(preview, f"Найближчі події (5 з {len(events)})" if len(events) > 5 else "Найближчі події")
    await message.answer(text, parse_mode="HTML", reply_markup=_main_kb(group_id))


@router.callback_query(F.data.startswith("ge_main_"))
async def cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    events = await api_client.get_group_events(group_id)
    preview = events[:5]
    text = _events_text(preview, f"Найближчі події (5 з {len(events)})" if len(events) > 5 else "Найближчі події")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_main_kb(group_id))
    await callback.answer()


# ── Full list ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_full_"))
async def cb_full(callback: CallbackQuery) -> None:
    group_id = int(callback.data.split("_")[2])
    events = await api_client.get_group_events(group_id)
    text = _events_text(events, "Всі події")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_full_kb(group_id))
    await callback.answer()


# ── Edit list ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_elist_"))
async def cb_elist(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    events = await api_client.get_group_events(group_id)
    if not events:
        await callback.answer("Подій немає.", show_alert=True)
        return
    await callback.message.edit_text(
        "<b>Оберіть подію для редагування:</b>",
        parse_mode="HTML",
        reply_markup=_elist_kb(events, group_id),
    )
    await callback.answer()


# ── Single event ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_ev_"))
async def cb_event(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = callback.data.split("_")
    group_id, event_id = int(parts[2]), int(parts[3])
    events = await api_client.get_group_events(group_id)
    ev = next((e for e in events if e["id"] == event_id), None)
    if ev is None:
        await callback.answer("Подію не знайдено.", show_alert=True)
        return
    await callback.message.edit_text(
        _event_card_text(ev), parse_mode="HTML", reply_markup=_event_kb(group_id, event_id)
    )
    await callback.answer()


# ── Delete ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_del_"))
async def cb_del_confirm(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    group_id, event_id = int(parts[2]), int(parts[3])
    await callback.message.edit_reply_markup(reply_markup=_del_confirm_kb(group_id, event_id))
    await callback.answer()


@router.callback_query(F.data.startswith("ge_delok_"))
async def cb_del_ok(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    group_id, event_id = int(parts[2]), int(parts[3])
    try:
        await api_client.delete_event(group_id, event_id)
    except Exception:
        logger.exception("Failed to delete event %s", event_id)
        await callback.answer("Помилка видалення.", show_alert=True)
        return
    events = await api_client.get_group_events(group_id)
    if not events:
        text = _events_text([], "Найближчі події")
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_main_kb(group_id))
    else:
        await callback.message.edit_text(
            "<b>Оберіть подію для редагування:</b>",
            parse_mode="HTML",
            reply_markup=_elist_kb(events, group_id),
        )
    await callback.answer("Видалено")


# ── Create ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_create_"))
async def cb_create(callback: CallbackQuery, state: FSMContext) -> None:
    group_id = int(callback.data.split("_")[2])
    await state.set_state(GEStates.create_name)
    await state.update_data(group_id=group_id)
    await callback.message.edit_reply_markup(reply_markup=_cancel_kb(f"ge_main_{group_id}"))
    await callback.message.answer("Введіть назву нової події:")
    await callback.answer()


@router.message(GEStates.create_name)
async def receive_create_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Назва не може бути порожньою. Введіть назву події:")
        return
    await state.update_data(name=name)
    await state.set_state(GEStates.create_date)
    await message.answer(
        "Введіть дату події (формат: дд.мм або дд.мм.рррр):",
        reply_markup=_cancel_kb(f"ge_manage_{(await state.get_data())['group_id']}"),
    )


@router.message(GEStates.create_date)
async def receive_create_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = message.text.strip() if message.text else ""
    parsed = _parse_date_input(text)
    if parsed is None:
        await message.answer("Невірний формат. Введіть дату як дд.мм або дд.мм.рррр:")
        return
    month, day, year = parsed
    await state.clear()
    try:
        await api_client.create_event(data["group_id"], {"name": data["name"], "month": month, "day": day, "year": year})
    except Exception:
        logger.exception("Failed to create event")
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return
    events = await api_client.get_group_events(data["group_id"])
    preview = events[:5]
    text_out = _events_text(preview, f"Найближчі події (5 з {len(events)})" if len(events) > 5 else "Найближчі події")
    await message.answer(text_out, parse_mode="HTML", reply_markup=_main_kb(data["group_id"]))


# ── Edit name ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_ename_"))
async def cb_edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    group_id, event_id = int(parts[2]), int(parts[3])
    await state.set_state(GEStates.edit_name)
    await state.update_data(group_id=group_id, event_id=event_id)
    await callback.message.edit_reply_markup(reply_markup=_cancel_kb(f"ge_ev_{group_id}_{event_id}"))
    await callback.message.answer("Введіть нову назву події:")
    await callback.answer()


@router.message(GEStates.edit_name)
async def receive_edit_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Назва не може бути порожньою:")
        return
    group_id, event_id = data["group_id"], data["event_id"]

    events = await api_client.get_group_events(group_id)
    ev = next((e for e in events if e["id"] == event_id), None)
    if ev is None:
        await state.clear()
        await message.answer("Подію не знайдено.")
        return

    await state.clear()
    try:
        updated = await api_client.update_event(group_id, event_id, {
            "name": name, "month": ev["month"], "day": ev["day"], "year": ev.get("year"),
        })
    except Exception:
        logger.exception("Failed to update event name")
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return
    await message.answer(_event_card_text(updated), parse_mode="HTML", reply_markup=_event_kb(group_id, event_id))


# ── Edit date ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ge_edate_"))
async def cb_edit_date(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    group_id, event_id = int(parts[2]), int(parts[3])
    await state.set_state(GEStates.edit_date)
    await state.update_data(group_id=group_id, event_id=event_id)
    await callback.message.edit_reply_markup(reply_markup=_cancel_kb(f"ge_ev_{group_id}_{event_id}"))
    await callback.message.answer("Введіть нову дату події (формат: дд.мм або дд.мм.рррр):")
    await callback.answer()


@router.message(GEStates.edit_date)
async def receive_edit_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = message.text.strip() if message.text else ""
    parsed = _parse_date_input(text)
    if parsed is None:
        await message.answer("Невірний формат. Введіть дату як дд.мм або дд.мм.рррр:")
        return
    month, day, year = parsed
    group_id, event_id = data["group_id"], data["event_id"]

    events = await api_client.get_group_events(group_id)
    ev = next((e for e in events if e["id"] == event_id), None)
    if ev is None:
        await state.clear()
        await message.answer("Подію не знайдено.")
        return

    await state.clear()
    try:
        updated = await api_client.update_event(group_id, event_id, {
            "name": ev["name"], "month": month, "day": day, "year": year,
        })
    except Exception:
        logger.exception("Failed to update event date")
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return
    await message.answer(_event_card_text(updated), parse_mode="HTML", reply_markup=_event_kb(group_id, event_id))


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_date_input(text: str) -> tuple[int, int, int | None] | None:
    """Parse dd.mm or dd.mm.yyyy → (month, day, year|None)"""
    parts = text.split(".")
    try:
        if len(parts) == 2:
            day, month = int(parts[0]), int(parts[1])
            year = None
        elif len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            return None
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return month, day, year
    except ValueError:
        return None
