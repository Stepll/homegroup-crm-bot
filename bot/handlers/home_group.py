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

MEETING_DAYS = {
    "Monday": "Понеділок",
    "Tuesday": "Вівторок",
    "Wednesday": "Середа",
    "Thursday": "Четвер",
    "Friday": "П'ятниця",
    "Saturday": "Субота",
    "Sunday": "Неділя",
}

SETTINGS_FIELDS = [
    ("name", "Назва"),
    ("description", "Опис"),
    ("meetingDay", "День зустрічі"),
    ("meetingTime", "Час початку"),
    ("meetingEndTime", "Час завершення"),
    ("location", "Місце"),
]
TEXT_SETTINGS = {"name", "description", "meetingTime", "meetingEndTime", "location"}


class HGStates(StatesGroup):
    waiting_field_value = State()
    waiting_new_date = State()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except Exception:
        return iso


def _fmt_time(t: str | None) -> str:
    return t[:5] if t else "—"


def _day_label(day: str | None) -> str:
    return MEETING_DAYS.get(day or "", day or "—")


def _e(v: str | None) -> str:
    return html.escape(v.strip()) if v and v.strip() else "—"


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


async def _get_admin_group_cb(callback: CallbackQuery) -> tuple[dict, int] | None:
    username = callback.from_user.username or ""
    admin = await find_admin_by_telegram(username)
    if admin is None:
        await callback.answer("Ваш акаунт не знайдено в CRM.")
        return None
    group_id = admin.get("primaryGroupId")
    if not group_id:
        await callback.answer("У вас не вказана основна група в CRM.")
        return None
    return admin, group_id


# ── Overview ─────────────────────────────────────────────────────────────────

def _overview_text(cabinet: dict) -> str:
    g = cabinet.get("group") or {}
    stats = cabinet.get("stats") or {}
    next_date = cabinet.get("nextMeetingDate")
    has_plan = cabinet.get("hasPlanForNextMeeting", False)
    conflicts = cabinet.get("nextMeetingConflicts") or []

    time_str = _fmt_time(g.get("meetingTime"))
    end_str = g.get("meetingEndTime")
    time_range = f"{time_str}–{_fmt_time(end_str)}" if end_str else time_str
    day = _day_label(g.get("meetingDay"))

    lines = [
        f"<b>{_e(g.get('name'))}</b>",
        "",
        f"День зустрічей: {day} о {time_range}",
        f"Місце: {_e(g.get('location'))}",
        f"Учасників: {stats.get('totalMembers', '—')}",
        "",
        f"Наступна зустріч: {_fmt_date(next_date) if next_date else '—'}",
        f"План: {'є' if has_plan else 'немає'}",
    ]

    for c in conflicts:
        t = f"{c.get('startTime', '')[:5]}–{c.get('endTime', '')[:5]}" if c.get("startTime") else ""
        lines.append(f"\n⚠️ Конфлікт: {html.escape(c.get('title', ''))} {t}".rstrip())

    return "\n".join(lines)


def _overview_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Статистика", callback_data=f"st_{group_id}_3m_1"),
            InlineKeyboardButton(text="Наступна домашка", callback_data="hg_next"),
        ],
        [
            InlineKeyboardButton(text="Учасники", callback_data=f"hg_members_{group_id}"),
            InlineKeyboardButton(text="Події домашки", callback_data=f"ge_main_{group_id}"),
        ],
        [InlineKeyboardButton(text="Записати потреби", callback_data="hg_record_needs")],
        [InlineKeyboardButton(text="Налаштування", callback_data="hg_settings")],
    ])


@router.message(F.text == "Домашка")
async def btn_home_group(message: Message, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result
    cabinet = await api_client.get_cabinet(group_id)
    await message.answer(_overview_text(cabinet), parse_mode="HTML", reply_markup=_overview_kb(group_id))


@router.callback_query(F.data == "hg_overview")
async def cb_overview(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group_cb(callback)
    if result is None:
        return
    _, group_id = result
    cabinet = await api_client.get_cabinet(group_id)
    await callback.message.edit_text(
        _overview_text(cabinet), parse_mode="HTML", reply_markup=_overview_kb(group_id)
    )
    await callback.answer()


# ── Settings ─────────────────────────────────────────────────────────────────

def _settings_text(group: dict) -> str:
    lines = [
        "<b>Налаштування групи</b>",
        "",
        f"Назва: {_e(group.get('name'))}",
        f"Опис: {_e(group.get('description'))}",
        f"День зустрічей: {_day_label(group.get('meetingDay'))}",
        f"Час початку: {_fmt_time(group.get('meetingTime'))}",
        f"Час завершення: {_fmt_time(group.get('meetingEndTime'))}",
        f"Місце: {_e(group.get('location'))}",
    ]
    return "\n".join(lines)


def _settings_view_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Редагувати", callback_data="hg_edit")],
        [InlineKeyboardButton(text="← Назад", callback_data="hg_overview")],
    ])


def _settings_edit_kb() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for key, label in SETTINGS_FIELDS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"hg_field_{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="hg_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _day_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"hg_day_{key}")]
        for key, label in MEETING_DAYS.items()
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="hg_edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cancel_kb(back: str = "hg_edit") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скасувати", callback_data=back)],
    ])


def _build_group_payload(group: dict, patch: dict) -> dict:
    merged = {
        "name": group.get("name") or "",
        "description": group.get("description"),
        "color": group.get("color") or "#6B7280",
        "meetingDay": group.get("meetingDay"),
        "meetingTime": group.get("meetingTime"),
        "meetingEndTime": group.get("meetingEndTime"),
        "location": group.get("location"),
        "leaderId": group.get("leaderId"),
        "isActive": group.get("isActive", True),
        "telegramGroupId": group.get("telegramGroupId"),
    }
    merged.update(patch)
    return merged


@router.callback_query(F.data == "hg_settings")
async def cb_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group_cb(callback)
    if result is None:
        return
    _, group_id = result
    group = await api_client.get_group(group_id)
    await callback.message.edit_text(
        _settings_text(group), parse_mode="HTML", reply_markup=_settings_view_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "hg_edit")
async def cb_settings_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=_settings_edit_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("hg_field_"))
async def cb_settings_field(callback: CallbackQuery, state: FSMContext) -> None:
    field_key = callback.data.removeprefix("hg_field_")

    if field_key == "meetingDay":
        await callback.message.edit_reply_markup(reply_markup=_day_kb())
        await callback.answer()
        return

    label = dict(SETTINGS_FIELDS).get(field_key, field_key)
    hint = " (формат: гг:хх, наприклад 18:00)" if "Time" in field_key else ""
    await state.set_state(HGStates.waiting_field_value)
    await state.update_data(field_key=field_key)
    await callback.message.edit_reply_markup(reply_markup=_cancel_kb())
    await callback.message.answer(f"Введіть нове значення для «{label}»{hint}:")
    await callback.answer()


@router.message(HGStates.waiting_field_value)
async def receive_settings_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field_key = data.get("field_key")
    await state.clear()

    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result

    value = message.text.strip() or None

    if field_key and "Time" in field_key and value:
        if len(value) == 5 and value[2] == ":":
            pass
        else:
            await message.answer("Невірний формат. Введіть час у форматі гг:хх (наприклад 18:00):")
            await state.set_state(HGStates.waiting_field_value)
            await state.update_data(**data)
            return

    group = await api_client.get_group(group_id)
    payload = _build_group_payload(group, {field_key: value})
    try:
        await api_client.update_group(group_id, payload)
    except Exception:
        logger.exception("Failed to update group field %s", field_key)
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return

    fresh = await api_client.get_group(group_id)
    await message.answer(
        _settings_text(fresh), parse_mode="HTML", reply_markup=_settings_view_kb()
    )


@router.callback_query(F.data.startswith("hg_day_"))
async def cb_settings_day(callback: CallbackQuery) -> None:
    value = callback.data.removeprefix("hg_day_")
    result = await _get_admin_group_cb(callback)
    if result is None:
        return
    _, group_id = result

    group = await api_client.get_group(group_id)
    payload = _build_group_payload(group, {"meetingDay": value})
    try:
        await api_client.update_group(group_id, payload)
    except Exception:
        logger.exception("Failed to update meetingDay")
        await callback.answer("Помилка збереження.")
        return

    fresh = await api_client.get_group(group_id)
    await callback.message.edit_text(
        _settings_text(fresh), parse_mode="HTML", reply_markup=_settings_view_kb()
    )
    await callback.answer("Збережено")


# ── Next meeting ──────────────────────────────────────────────────────────────

def _next_meeting_text(cabinet: dict) -> str:
    next_date = cabinet.get("nextMeetingDate")
    g = cabinet.get("group") or {}
    day = _day_label(g.get("meetingDay"))

    if next_date:
        try:
            weekday = datetime.fromisoformat(next_date[:10]).strftime("%A")
            day_ua = MEETING_DAYS.get(weekday, day)
        except Exception:
            day_ua = day
        date_str = f"{_fmt_date(next_date)} ({day_ua})"
    else:
        date_str = "невідома"

    return f"<b>Наступна зустріч</b>\n\nДата: {date_str}"


def _next_meeting_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Пропустити", callback_data="hg_skip"),
            InlineKeyboardButton(text="Перенести", callback_data="hg_reschedule"),
        ],
        [InlineKeyboardButton(text="← Домашка", callback_data="hg_overview")],
    ])


@router.message(F.text == "Наступна домашка")
async def btn_next_meeting(message: Message, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result
    cabinet = await api_client.get_cabinet(group_id)
    await message.answer(
        _next_meeting_text(cabinet), parse_mode="HTML", reply_markup=_next_meeting_kb()
    )


@router.callback_query(F.data == "hg_next")
async def cb_next_meeting(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group_cb(callback)
    if result is None:
        return
    _, group_id = result
    cabinet = await api_client.get_cabinet(group_id)
    await callback.message.edit_text(
        _next_meeting_text(cabinet), parse_mode="HTML", reply_markup=_next_meeting_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "hg_skip")
async def cb_skip_meeting(callback: CallbackQuery) -> None:
    result = await _get_admin_group_cb(callback)
    if result is None:
        return
    _, group_id = result
    try:
        await api_client.skip_meeting(group_id)
    except Exception:
        logger.exception("Failed to skip meeting")
        await callback.answer("Помилка. Спробуйте ще раз.")
        return

    cabinet = await api_client.get_cabinet(group_id)
    await callback.message.edit_text(
        _next_meeting_text(cabinet), parse_mode="HTML", reply_markup=_next_meeting_kb()
    )
    await callback.answer("Зустріч пропущено")


@router.callback_query(F.data == "hg_reschedule")
async def cb_reschedule(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(HGStates.waiting_new_date)
    await callback.message.edit_reply_markup(
        reply_markup=_cancel_kb(back="hg_next")
    )
    await callback.message.answer("Введіть нову дату зустрічі (формат: дд.мм.рррр):")
    await callback.answer()


@router.message(HGStates.waiting_new_date)
async def receive_new_date(message: Message, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result

    try:
        date_iso = datetime.strptime(message.text.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        await message.answer("Невірний формат. Введіть дату у форматі дд.мм.рррр:")
        await state.set_state(HGStates.waiting_new_date)
        return

    try:
        await api_client.set_next_meeting(group_id, date_iso)
    except Exception:
        logger.exception("Failed to set next meeting")
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return

    cabinet = await api_client.get_cabinet(group_id)
    await message.answer(
        _next_meeting_text(cabinet), parse_mode="HTML", reply_markup=_next_meeting_kb()
    )
