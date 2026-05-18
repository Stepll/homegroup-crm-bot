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
router.callback_query.filter(F.message.chat.type == "private")
router.message.filter(F.chat.type == "private")

logger = logging.getLogger(__name__)

GENDER_OPTIONS = [("Male", "Чоловіча"), ("Female", "Жіноча")]
MARITAL_OPTIONS = [
    ("Single", "Неодружений/а"),
    ("Married", "Одружений/а"),
    ("Divorced", "Розлучений/а"),
    ("Widowed", "Вдів/Вдова"),
]

PERSON_FIELDS = [
    ("name", "Ім'я"), ("lastName", "Прізвище"),
    ("phone", "Телефон"), ("email", "Email"),
    ("telegram", "Telegram"), ("gender", "Стать"),
    ("maritalStatus", "Сімейний стан"), ("address", "Адреса"),
    ("dateOfBirth", "Дата народження"), ("isBaptized", "Хрещений водою"),
    ("isBaptizedWithSpirit", "Хрещений Духом"), ("church", "Церква"),
    ("ministry", "Служіння"), ("notes", "Нотатки"),
]
ADMIN_FIELDS = [
    ("name", "Ім'я"), ("lastName", "Прізвище"),
    ("phone", "Телефон"), ("telegram", "Telegram"),
    ("gender", "Стать"), ("maritalStatus", "Сімейний стан"),
    ("address", "Адреса"), ("dateOfBirth", "Дата народження"),
    ("isBaptized", "Хрещений водою"), ("isBaptizedWithSpirit", "Хрещений Духом"),
    ("church", "Церква"), ("ministry", "Служіння"),
]

BOOL_FIELDS = {"isBaptized", "isBaptizedWithSpirit"}
DATE_FIELDS = {"dateOfBirth"}
ALL_FIELD_LABELS = dict(PERSON_FIELDS + ADMIN_FIELDS)


class MemberStates(StatesGroup):
    waiting_value = State()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _e(v) -> str:
    s = str(v).strip() if v is not None else ""
    return html.escape(s) if s else "—"


def _fmt_date(iso) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except Exception:
        return str(iso)


def _find_stat(stats: dict, is_admin: bool, member_id: int) -> dict | None:
    for s in stats.get("personStats") or []:
        key = "userId" if is_admin else "personId"
        if s.get(key) == member_id:
            return s
    return None


# ── Members list ──────────────────────────────────────────────────────────────

async def _build_members_list(group_id: int) -> tuple[str, InlineKeyboardMarkup]:
    members, stats = await _fetch_members_and_stats(group_id)

    stat_by_pid = {s["personId"]: s for s in (stats.get("personStats") or []) if s.get("personId")}
    stat_by_uid = {s["userId"]: s for s in (stats.get("personStats") or []) if s.get("userId")}

    meetings = sorted(stats.get("meetings") or [], key=lambda x: x["date"])
    lines = ["<b>Відвідуваність за місяць:</b>", ""]
    if meetings:
        for m in meetings:
            d = _fmt_date(m["date"])
            pct = int(m["attendanceRate"] * 100)
            lines.append(f"{d} — {m['presentCount']}/{m['totalMembers']} ({pct}%)")
    else:
        lines.append("Зустрічей за цей місяць не знайдено.")
    lines += ["", "<b>Учасники:</b>"]

    rows = []
    for m in members:
        is_admin = m.get("isAdmin", False)
        member_id = m.get("userId") if is_admin else m.get("id")
        stat = stat_by_uid.get(member_id) if is_admin else stat_by_pid.get(member_id)
        absent = (stat["totalMeetings"] - stat["presentCount"]) if stat else 0

        name = f"{m.get('name', '')} {m.get('lastName') or ''}".strip()
        label = f"{'⚠️ ' if absent > 4 else ''}{name}"
        tc = "u" if is_admin else "p"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"mem_{tc}_{group_id}_{member_id}",
        )])

    rows.append([InlineKeyboardButton(text="← Назад", callback_data="hg_overview")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "Учасники")
async def btn_members(message: Message, state: FSMContext) -> None:
    await state.clear()
    username = message.from_user.username if message.from_user else None
    admin = await find_admin_by_telegram(username or "")
    if admin is None:
        await message.answer("Ваш акаунт не знайдено в CRM.")
        return
    group_id = admin.get("primaryGroupId")
    if not group_id:
        await message.answer("У вас не вказана основна група в CRM.")
        return
    text, kb = await _build_members_list(group_id)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("hg_members_"))
async def cb_members_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    text, kb = await _build_members_list(group_id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def _fetch_members_and_stats(group_id: int) -> tuple[list, dict]:
    members = await api_client.get_group_members(group_id)
    stats = await api_client.get_group_stats(group_id, "1m")
    return members, stats


# ── Member card ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mem_"))
async def cb_member_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = callback.data.split("_")
    tc, group_id, member_id = parts[1], int(parts[2]), int(parts[3])
    is_admin = tc == "u"

    if is_admin:
        member = await api_client.get_admin(member_id)
    else:
        member = await api_client.get_person(member_id)

    stats = await api_client.get_group_stats(group_id, "1m")
    stat = _find_stat(stats, is_admin, member_id)

    await callback.message.edit_text(
        _format_card(member, is_admin, stat),
        parse_mode="HTML",
        reply_markup=_card_view_kb(tc, group_id, member_id),
    )
    await callback.answer()


def _format_card(member: dict, is_admin: bool, stat: dict | None) -> str:
    name = html.escape(
        f"{member.get('name') or ''} {member.get('lastName') or ''}".strip() or "—"
    )
    label = " <i>(Адмін)</i>" if is_admin else ""
    tg_raw = member.get("telegram") or ""
    tg = html.escape("@" + tg_raw.lstrip("@")) if tg_raw.strip() else "—"
    gender = dict(GENDER_OPTIONS).get(member.get("gender") or "", "—")
    marital = dict(MARITAL_OPTIONS).get(member.get("maritalStatus") or "", "—")

    lines = [
        f"<b>{name}</b>{label}", "",
        f"Телефон: {_e(member.get('phone'))}",
        f"Telegram: {tg}",
    ]
    if not is_admin:
        lines.append(f"Email: {_e(member.get('email'))}")
    lines += [
        f"Стать: {gender}",
        f"Сімейний стан: {marital}",
        f"Дата народження: {_fmt_date(member.get('dateOfBirth'))}",
        f"Хрещений водою: {'Так' if member.get('isBaptized') else 'Ні'}",
        f"Хрещений Духом: {'Так' if member.get('isBaptizedWithSpirit') else 'Ні'}",
        f"Церква: {_e(member.get('church'))}",
        f"Служіння: {_e(member.get('ministry'))}",
        f"Адреса: {_e(member.get('address'))}",
        f"Статус: {_e((member.get('status') or {}).get('name'))}",
    ]
    if not is_admin:
        lines.append(f"Нотатки: {_e(member.get('notes'))}")

    if stat:
        pct = int(stat["attendanceRate"] * 100)
        lines += [
            "",
            f"📊 За місяць: {stat['presentCount']} з {stat['totalMeetings']} зустрічей ({pct}%)",
        ]

    return "\n".join(lines)


def _card_view_kb(tc: str, group_id: int, member_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Редагувати", callback_data=f"medit_{tc}_{group_id}_{member_id}")],
        [InlineKeyboardButton(text="← Назад", callback_data=f"hg_members_{group_id}")],
    ])


# ── Edit menu ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("medit_"))
async def cb_edit_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = callback.data.split("_")
    tc, group_id, member_id = parts[1], int(parts[2]), int(parts[3])
    fields = ADMIN_FIELDS if tc == "u" else PERSON_FIELDS
    await callback.message.edit_reply_markup(reply_markup=_edit_kb(fields, tc, group_id, member_id))
    await callback.answer()


def _edit_kb(fields: list, tc: str, group_id: int, member_id: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, label in fields:
        row.append(InlineKeyboardButton(text=label, callback_data=f"mf_{key}_{tc}_{group_id}_{member_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"mem_{tc}_{group_id}_{member_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Field tap ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mf_"))
async def cb_field(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    field_key, tc, group_id, member_id = parts[1], parts[2], int(parts[3]), int(parts[4])
    label = ALL_FIELD_LABELS.get(field_key, field_key)

    if field_key in BOOL_FIELDS:
        await callback.message.edit_reply_markup(reply_markup=_bool_kb(field_key, tc, group_id, member_id))
    elif field_key == "gender":
        await callback.message.edit_reply_markup(reply_markup=_gender_kb(tc, group_id, member_id))
    elif field_key == "maritalStatus":
        await callback.message.edit_reply_markup(reply_markup=_marital_kb(tc, group_id, member_id))
    else:
        hint = " (формат: дд.мм.рррр)" if field_key in DATE_FIELDS else ""
        await state.set_state(MemberStates.waiting_value)
        await state.update_data(field_key=field_key, tc=tc, group_id=group_id, member_id=member_id)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Скасувати", callback_data=f"mcancel_{tc}_{group_id}_{member_id}")
        ]])
        await callback.message.edit_reply_markup(reply_markup=cancel_kb)
        await callback.message.answer(f"Введіть нове значення для «{label}»{hint}:")

    await callback.answer()


@router.callback_query(F.data.startswith("mcancel_"))
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = callback.data.split("_")
    tc, group_id, member_id = parts[1], int(parts[2]), int(parts[3])
    fields = ADMIN_FIELDS if tc == "u" else PERSON_FIELDS
    await callback.message.edit_reply_markup(reply_markup=_edit_kb(fields, tc, group_id, member_id))
    await callback.answer()


# ── Choice keyboards ──────────────────────────────────────────────────────────

def _bool_kb(field_key: str, tc: str, group_id: int, member_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так", callback_data=f"mbool_{field_key}_true_{tc}_{group_id}_{member_id}"),
            InlineKeyboardButton(text="Ні", callback_data=f"mbool_{field_key}_false_{tc}_{group_id}_{member_id}"),
        ],
        [InlineKeyboardButton(text="← Назад", callback_data=f"medit_{tc}_{group_id}_{member_id}")],
    ])


def _gender_kb(tc: str, group_id: int, member_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=lbl, callback_data=f"mgender_{val}_{tc}_{group_id}_{member_id}")
         for val, lbl in GENDER_OPTIONS],
        [InlineKeyboardButton(text="← Назад", callback_data=f"medit_{tc}_{group_id}_{member_id}")],
    ])


def _marital_kb(tc: str, group_id: int, member_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=lbl, callback_data=f"mmarital_{val}_{tc}_{group_id}_{member_id}")]
        for val, lbl in MARITAL_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"medit_{tc}_{group_id}_{member_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Bool / enum callbacks ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mbool_"))
async def cb_bool(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    field_key, str_val, tc, group_id, member_id = parts[1], parts[2], parts[3], int(parts[4]), int(parts[5])
    await _save_and_refresh_cb(callback, tc, group_id, member_id, {field_key: str_val == "true"})


@router.callback_query(F.data.startswith("mgender_"))
async def cb_gender(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    val, tc, group_id, member_id = parts[1], parts[2], int(parts[3]), int(parts[4])
    await _save_and_refresh_cb(callback, tc, group_id, member_id, {"gender": val})


@router.callback_query(F.data.startswith("mmarital_"))
async def cb_marital(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    val, tc, group_id, member_id = parts[1], parts[2], int(parts[3]), int(parts[4])
    await _save_and_refresh_cb(callback, tc, group_id, member_id, {"maritalStatus": val})


# ── Text input ────────────────────────────────────────────────────────────────

@router.message(MemberStates.waiting_value)
async def receive_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field_key, tc, group_id, member_id = data["field_key"], data["tc"], data["group_id"], data["member_id"]
    await state.clear()

    value = message.text.strip() or None
    if field_key in DATE_FIELDS and value:
        try:
            value = datetime.strptime(value, "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            await message.answer("Невірний формат. Введіть дату у форматі дд.мм.рррр:")
            await state.set_state(MemberStates.waiting_value)
            await state.update_data(**data)
            return

    is_admin = tc == "u"
    try:
        if is_admin:
            member = await api_client.get_admin(member_id)
            await api_client.update_profile(member_id, _admin_payload(member, {field_key: value}))
            fresh = await api_client.get_admin(member_id)
        else:
            member = await api_client.get_person(member_id)
            await api_client.update_person(member_id, _person_payload(member, {field_key: value}))
            fresh = await api_client.get_person(member_id)
    except Exception:
        logger.exception("Failed to update member %s field %s", member_id, field_key)
        await message.answer("Помилка збереження. Спробуйте ще раз.")
        return

    stats = await api_client.get_group_stats(group_id, "1m")
    stat = _find_stat(stats, is_admin, member_id)
    await message.answer(
        _format_card(fresh, is_admin, stat),
        parse_mode="HTML",
        reply_markup=_card_view_kb(tc, group_id, member_id),
    )


# ── Save helpers ──────────────────────────────────────────────────────────────

async def _save_and_refresh_cb(
    callback: CallbackQuery, tc: str, group_id: int, member_id: int, patch: dict
) -> None:
    is_admin = tc == "u"
    try:
        if is_admin:
            member = await api_client.get_admin(member_id)
            await api_client.update_profile(member_id, _admin_payload(member, patch))
            fresh = await api_client.get_admin(member_id)
        else:
            member = await api_client.get_person(member_id)
            await api_client.update_person(member_id, _person_payload(member, patch))
            fresh = await api_client.get_person(member_id)
    except Exception:
        logger.exception("Failed to update member %s", member_id)
        await callback.answer("Помилка збереження.")
        return

    stats = await api_client.get_group_stats(group_id, "1m")
    stat = _find_stat(stats, is_admin, member_id)
    await callback.message.edit_text(
        _format_card(fresh, is_admin, stat),
        parse_mode="HTML",
        reply_markup=_card_view_kb(tc, group_id, member_id),
    )
    await callback.answer("Збережено")


# ── Payload builders ──────────────────────────────────────────────────────────

def _person_payload(person: dict, patch: dict) -> dict:
    dob = person.get("dateOfBirth")
    merged = {
        "name": person.get("name") or "",
        "lastName": person.get("lastName"),
        "phone": person.get("phone"),
        "email": person.get("email"),
        "telegram": person.get("telegram"),
        "notes": person.get("notes"),
        "gender": person.get("gender"),
        "maritalStatus": person.get("maritalStatus"),
        "address": person.get("address"),
        "dateOfBirth": str(dob)[:10] if dob else None,
        "isBaptized": bool(person.get("isBaptized")),
        "church": person.get("church"),
        "ministry": person.get("ministry"),
        "isBaptizedWithSpirit": bool(person.get("isBaptizedWithSpirit")),
        "personStatusId": (person.get("status") or {}).get("id"),
        "oversightInfo": person.get("oversightInfo"),
        "oversightUserId": person.get("oversightUserId"),
        "primaryGroupId": person.get("primaryGroupId"),
    }
    merged.update(patch)
    return merged


def _admin_payload(admin: dict, patch: dict) -> dict:
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
