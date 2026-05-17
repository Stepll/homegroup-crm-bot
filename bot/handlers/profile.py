import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.api_client import api_client

router = Router()
router.message.filter(ChatType("private"))
router.callback_query.filter(ChatType("private"))

logger = logging.getLogger(__name__)

GENDER_OPTIONS = [("Male", "Чоловіча"), ("Female", "Жіноча")]
MARITAL_OPTIONS = [
    ("Single", "Неодружений/а"),
    ("Married", "Одружений/а"),
    ("Divorced", "Розлучений/а"),
    ("Widowed", "Вдів/Вдова"),
]

TEXT_FIELDS = {
    "name": "Ім'я",
    "lastName": "Прізвище",
    "phone": "Телефон",
    "address": "Адреса",
    "church": "Церква",
    "ministry": "Служіння",
}
DATE_FIELDS = {"dateOfBirth": "Дата народження"}
BOOL_FIELDS = {"isBaptized": "Хрещений водою", "isBaptizedWithSpirit": "Хрещений Духом"}
ENUM_FIELDS = {"gender": "Стать", "maritalStatus": "Сімейний стан"}
ALL_FIELD_LABELS = {**TEXT_FIELDS, **DATE_FIELDS, **BOOL_FIELDS, **ENUM_FIELDS}

EDIT_FIELDS_ORDER = [
    ("name", "Ім'я"),
    ("lastName", "Прізвище"),
    ("phone", "Телефон"),
    ("address", "Адреса"),
    ("dateOfBirth", "Дата народження"),
    ("church", "Церква"),
    ("ministry", "Служіння"),
    ("isBaptized", "Хрещений водою"),
    ("isBaptizedWithSpirit", "Хрещений Духом"),
    ("gender", "Стать"),
    ("maritalStatus", "Сімейний стан"),
]


class ProfileStates(StatesGroup):
    waiting_field_value = State()


# --- Helpers ---

async def _find_admin_by_username(username: str) -> dict | None:
    username_clean = username.lstrip("@").lower()
    try:
        admins = await api_client.get_admins()
        for admin in admins:
            tg = (admin.get("telegram") or "").lstrip("@").lower()
            if tg and tg == username_clean:
                return admin
    except Exception:
        logger.exception("Failed to fetch admins for profile lookup")
    return None


def _format_profile(admin: dict) -> str:
    def val(v: str | None) -> str:
        return v.strip() if v and v.strip() else "—"

    gender_map = dict(GENDER_OPTIONS)
    marital_map = dict(MARITAL_OPTIONS)

    dob_raw = admin.get("dateOfBirth")
    dob = "—"
    if dob_raw:
        try:
            dob = datetime.fromisoformat(dob_raw[:10]).strftime("%d.%m.%Y")
        except ValueError:
            dob = dob_raw[:10]

    name_parts = [admin.get("name") or "", admin.get("lastName") or ""]
    full_name = " ".join(p for p in name_parts if p).strip() or "—"

    tg_raw = admin.get("telegram") or ""
    tg = ("@" + tg_raw.lstrip("@")) if tg_raw.strip() else "—"

    roles = ", ".join(r.get("name", "") for r in (admin.get("roles") or []))
    status_name = (admin.get("status") or {}).get("name") or ""
    group_name = val(admin.get("primaryGroupName"))

    lines = [
        f"*{full_name}*",
        "",
        f"Телефон: {val(admin.get('phone'))}",
        f"Telegram: {tg}",
        f"Email: {val(admin.get('email'))}",
        f"Стать: {gender_map.get(admin.get('gender') or '', val(admin.get('gender')))}",
        f"Сімейний стан: {marital_map.get(admin.get('maritalStatus') or '', val(admin.get('maritalStatus')))}",
        f"Дата народження: {dob}",
        f"Хрещений водою: {'Так' if admin.get('isBaptized') else 'Ні'}",
        f"Хрещений Духом: {'Так' if admin.get('isBaptizedWithSpirit') else 'Ні'}",
        f"Церква: {val(admin.get('church'))}",
        f"Служіння: {val(admin.get('ministry'))}",
        f"Адреса: {val(admin.get('address'))}",
        f"Статус: {status_name or '—'}",
        f"Ролі: {roles or '—'}",
        f"Група: {group_name}",
    ]
    return "\n".join(lines)


def _build_profile_payload(admin: dict, patch: dict) -> dict:
    """Merge current admin values with a single-field patch into a full profile payload."""
    merged = {
        "name": admin.get("name"),
        "lastName": admin.get("lastName"),
        "phone": admin.get("phone"),
        "telegram": admin.get("telegram"),
        "notes": admin.get("notes"),
        "gender": admin.get("gender"),
        "maritalStatus": admin.get("maritalStatus"),
        "address": admin.get("address"),
        "dateOfBirth": admin.get("dateOfBirth"),
        "isBaptized": bool(admin.get("isBaptized")),
        "church": admin.get("church"),
        "ministry": admin.get("ministry"),
        "isBaptizedWithSpirit": bool(admin.get("isBaptizedWithSpirit")),
        "personStatusId": (admin.get("status") or {}).get("id"),
    }
    merged.update(patch)
    return merged


# --- Keyboards ---

def _profile_view_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Редагувати", callback_data="prof_edit")],
    ])


def _profile_edit_kb() -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for key, label in EDIT_FIELDS_ORDER:
        row.append(InlineKeyboardButton(text=label, callback_data=f"prof_field_{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="prof_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bool_kb(field_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так", callback_data=f"prof_bool_{field_key}_true"),
            InlineKeyboardButton(text="Ні", callback_data=f"prof_bool_{field_key}_false"),
        ],
        [InlineKeyboardButton(text="← Назад", callback_data="prof_edit")],
    ])


def _gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"prof_gender_{value}")
         for value, label in GENDER_OPTIONS],
        [InlineKeyboardButton(text="← Назад", callback_data="prof_edit")],
    ])


def _marital_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"prof_marital_{value}")]
        for value, label in MARITAL_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="prof_edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скасувати", callback_data="prof_edit")],
    ])


# --- Handlers ---

@router.message(F.text == "Профіль")
async def btn_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    username = message.from_user.username if message.from_user else None
    if not username:
        await message.answer("Не вдалося ідентифікувати ваш акаунт.")
        return
    admin = await _find_admin_by_username(username)
    if admin is None:
        await message.answer("Ваш акаунт не знайдено в CRM.")
        return
    await message.answer(
        _format_profile(admin),
        parse_mode="Markdown",
        reply_markup=_profile_view_kb(),
    )


@router.callback_query(F.data == "prof_edit")
async def cb_prof_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=_profile_edit_kb())
    await callback.answer()


@router.callback_query(F.data == "prof_back")
async def cb_prof_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    username = callback.from_user.username
    admin = await _find_admin_by_username(username) if username else None
    if admin is None:
        await callback.answer("Не вдалося завантажити профіль.")
        return
    await callback.message.edit_text(
        _format_profile(admin),
        parse_mode="Markdown",
        reply_markup=_profile_view_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prof_field_"))
async def cb_prof_field(callback: CallbackQuery, state: FSMContext) -> None:
    field_key = callback.data.removeprefix("prof_field_")

    if field_key in BOOL_FIELDS:
        await callback.message.edit_reply_markup(reply_markup=_bool_kb(field_key))
        await callback.answer()
        return
    if field_key == "gender":
        await callback.message.edit_reply_markup(reply_markup=_gender_kb())
        await callback.answer()
        return
    if field_key == "maritalStatus":
        await callback.message.edit_reply_markup(reply_markup=_marital_kb())
        await callback.answer()
        return

    label = ALL_FIELD_LABELS.get(field_key, field_key)
    hint = " (формат: дд.мм.рррр)" if field_key == "dateOfBirth" else ""
    await state.set_state(ProfileStates.waiting_field_value)
    await state.update_data(field_key=field_key)
    await callback.message.edit_reply_markup(reply_markup=_cancel_kb())
    await callback.message.answer(f"Введіть нове значення для «{label}»{hint}:")
    await callback.answer()


@router.message(ProfileStates.waiting_field_value)
async def receive_field_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field_key = data.get("field_key")
    await state.clear()

    username = message.from_user.username if message.from_user else None
    admin = await _find_admin_by_username(username) if username else None
    if admin is None:
        await message.answer("Не вдалося знайти ваш акаунт.")
        return

    value = message.text.strip()

    if field_key == "dateOfBirth":
        try:
            value = datetime.strptime(value, "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            await message.answer("Невірний формат. Введіть дату у форматі дд.мм.рррр:")
            await state.set_state(ProfileStates.waiting_field_value)
            await state.update_data(**data)
            return

    await _save_and_show(message, admin, {field_key: value})


@router.callback_query(F.data.startswith("prof_bool_"))
async def cb_prof_bool(callback: CallbackQuery) -> None:
    # format: prof_bool_{field_key}_{true|false}
    rest = callback.data.removeprefix("prof_bool_")
    field_key, str_val = rest.rsplit("_", 1)
    value = str_val == "true"
    admin = await _find_admin_by_username(callback.from_user.username or "")
    if admin is None:
        await callback.answer("Не вдалося знайти ваш акаунт.")
        return
    await _save_and_show_cb(callback, admin, {field_key: value})


@router.callback_query(F.data.startswith("prof_gender_"))
async def cb_prof_gender(callback: CallbackQuery) -> None:
    value = callback.data.removeprefix("prof_gender_")
    admin = await _find_admin_by_username(callback.from_user.username or "")
    if admin is None:
        await callback.answer("Не вдалося знайти ваш акаунт.")
        return
    await _save_and_show_cb(callback, admin, {"gender": value})


@router.callback_query(F.data.startswith("prof_marital_"))
async def cb_prof_marital(callback: CallbackQuery) -> None:
    value = callback.data.removeprefix("prof_marital_")
    admin = await _find_admin_by_username(callback.from_user.username or "")
    if admin is None:
        await callback.answer("Не вдалося знайти ваш акаунт.")
        return
    await _save_and_show_cb(callback, admin, {"maritalStatus": value})


# --- Save helpers ---

async def _save_and_show(message: Message, admin: dict, patch: dict) -> None:
    payload = _build_profile_payload(admin, patch)
    try:
        await api_client.update_profile(admin["id"], payload)
    except Exception:
        logger.exception("Failed to update profile")
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return
    fresh = await api_client.get_admin(admin["id"])
    await message.answer(
        _format_profile(fresh),
        parse_mode="Markdown",
        reply_markup=_profile_view_kb(),
    )


async def _save_and_show_cb(callback: CallbackQuery, admin: dict, patch: dict) -> None:
    payload = _build_profile_payload(admin, patch)
    try:
        await api_client.update_profile(admin["id"], payload)
    except Exception:
        logger.exception("Failed to update profile")
        await callback.answer("Помилка збереження.")
        return
    fresh = await api_client.get_admin(admin["id"])
    await callback.message.edit_text(
        _format_profile(fresh),
        parse_mode="Markdown",
        reply_markup=_profile_view_kb(),
    )
    await callback.answer("Збережено")
