"""
Record needs flow — group/private chat.

Entry points:
1. /record_needs slash command in leader (group) chat
2. Auto-trigger 30 min before meetingEndTime — sent to leader chat
3. "Записати потреби" button in private chat (from Домашка inline menu) → report stays private
"""
from __future__ import annotations

import html
import logging
import secrets
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client
from bot.utils import find_admin_by_telegram

router = Router()
logger = logging.getLogger(__name__)


class RecordNeedsStates(StatesGroup):
    waiting_guest_name = State()
    waiting_need_text = State()


# chat_id → {sid: str, msg_id: int, user_id: int | None}
# Active session per chat (only one prompt visible at a time per chat).
ACTIVE_SESSIONS: dict[int, dict] = {}

INITIAL_TEXT = "<b>Записати потреби членів домашки?</b>"


def _new_sid() -> str:
    return secrets.token_hex(3)


def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")


def _fmt_date_uk(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except Exception:
        return iso


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _find_group_by_chat(chat_id: int) -> dict | None:
    groups = await api_client.get_groups()
    return next((g for g in groups if g.get("telegramGroupId") == str(chat_id)), None)


async def _admin_primary_group(username: str | None) -> int | None:
    if not username:
        return None
    admin = await find_admin_by_telegram(username)
    if not admin:
        return None
    return admin.get("primaryGroupId")


async def _build_candidates(group_id: int, meeting_date: str) -> tuple[list[dict], bool]:
    """Returns (candidates [{tc, id, name}], has_attendance) — sorted alphabetically."""
    members = await api_client.get_group_members(group_id)
    members = [m for m in members if not m.get("isFormer")]

    try:
        attendance = await api_client.get_attendance(group_id, meeting_date)
    except Exception:
        attendance = []
    present_pids = {a["personId"] for a in attendance if a.get("personId") and a.get("wasPresent")}
    present_uids = {a["userId"] for a in attendance if a.get("userId") and a.get("wasPresent")}
    has_attendance = bool(present_pids or present_uids)

    out: list[dict] = []
    for m in members:
        is_admin = m.get("isAdmin", False)
        mid = m.get("userId") if is_admin else m.get("id")
        if mid is None:
            continue
        tc = "u" if is_admin else "p"
        if has_attendance:
            in_present = mid in (present_uids if is_admin else present_pids)
            if not in_present:
                continue
        full = f"{m.get('name') or ''} {m.get('lastName') or ''}".strip() or "—"
        out.append({"tc": tc, "id": mid, "name": full, "telegram": m.get("telegram") or ""})

    out.sort(key=lambda c: c["name"].lower())
    return out, has_attendance


# ── Keyboards ──────────────────────────────────────────────────────────────────

def _initial_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Скасувати", callback_data=f"rn_can_{sid}"),
            InlineKeyboardButton(text="Розпочати запис", callback_data=f"rn_go_{sid}"),
        ],
    ])


def _picker_kb(sid: str, candidates: list[dict], recorded_keys: set[tuple]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="+ Гість", callback_data=f"rn_gu_{sid}")]
    ]
    row: list[InlineKeyboardButton] = []
    for c in candidates:
        mark = "✓ " if (c["tc"], c["id"]) in recorded_keys else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{c['name']}",
            callback_data=f"rn_pk_{sid}_{c['tc']}_{c['id']}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="Скасувати", callback_data=f"rn_can_{sid}"),
        InlineKeyboardButton(text="Готово", callback_data=f"rn_dn_{sid}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _force_reply(placeholder: str) -> ForceReply:
    # selective so only the starter sees the reply prompt (group chats);
    # bypasses bot privacy mode because the user's reply targets the bot.
    return ForceReply(selective=True, input_field_placeholder=placeholder)


async def _clear_prompt(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Delete any pending ForceReply prompt message tracked in FSM data."""
    data = await state.get_data()
    pmsg = data.get("prompt_msg_id")
    if pmsg:
        try:
            await bot.delete_message(chat_id, pmsg)
        except Exception:
            pass
        await state.update_data(prompt_msg_id=None)


def _picker_text(meeting_date: str | None, has_attendance: bool) -> str:
    header = f"<b>Запис потреб {_fmt_date_uk(meeting_date)}</b>"
    if not has_attendance:
        header += "\n<i>За цю зустріч відмічань не було. Показані всі члени домашки.</i>"
    return header + "\n\nОберіть кого додати:"


# ── Initial prompt (shared) ────────────────────────────────────────────────────

async def _send_initial(
    bot: Bot, chat_id: int, *, edit_message_id: int | None = None,
) -> tuple[str, int]:
    """Send/edit initial prompt. Returns (sid, msg_id). Deduplicates old prompt in same chat."""
    prior = ACTIVE_SESSIONS.get(chat_id)
    if prior and prior.get("msg_id") and prior["msg_id"] != edit_message_id:
        try:
            await bot.delete_message(chat_id, prior["msg_id"])
        except Exception:
            pass

    sid = _new_sid()

    if edit_message_id is not None:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=edit_message_id,
            text=INITIAL_TEXT, parse_mode="HTML", reply_markup=_initial_kb(sid),
        )
        msg_id = edit_message_id
    else:
        sent = await bot.send_message(
            chat_id, INITIAL_TEXT, parse_mode="HTML", reply_markup=_initial_kb(sid),
        )
        msg_id = sent.message_id

    ACTIVE_SESSIONS[chat_id] = {"sid": sid, "msg_id": msg_id, "user_id": None}
    return sid, msg_id


# Public API for scheduler
async def send_record_needs_prompt(bot: Bot, chat_id: int) -> None:
    await _send_initial(bot, chat_id)


# ── Entry: /record_needs in group chat ─────────────────────────────────────────

@router.message(Command("record_needs"))
async def cmd_record_needs(message: Message, bot: Bot) -> None:
    if message.chat.type == "private":
        await message.answer("Ця команда працює тільки в груповому чаті лідерів.")
        return

    group = await _find_group_by_chat(message.chat.id)
    if not group:
        await message.answer("Цей чат не привʼязаний до домашки в CRM.")
        return

    await _send_initial(bot, message.chat.id)
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass


# ── Entry: "Записати потреби" from private chat (Домашка inline kb) ────────────

@router.callback_query(F.data == "hg_record_needs")
async def cb_record_needs_private(callback: CallbackQuery, bot: Bot) -> None:
    if callback.message.chat.type != "private":
        return
    group_id = await _admin_primary_group(callback.from_user.username)
    if group_id is None:
        await callback.answer("Ваш акаунт не знайдено або немає основної групи.", show_alert=True)
        return

    await _send_initial(bot, callback.message.chat.id, edit_message_id=callback.message.message_id)
    await callback.answer()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_session(callback: CallbackQuery, sid: str) -> bool:
    return ACTIVE_SESSIONS.get(callback.message.chat.id, {}).get("sid") == sid


async def _check_starter(callback: CallbackQuery, state: FSMContext) -> bool:
    data = await state.get_data()
    starter = data.get("starter_user_id")
    if starter is None:
        return True  # not yet claimed
    return starter == callback.from_user.id


# ── Initial: Cancel / Start ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rn_can_"))
async def cb_cancel(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    sid = callback.data.split("_", 2)[2]
    if not _check_session(callback, sid):
        await callback.answer("Цей запис вже завершено.", show_alert=True)
        return
    if not await _check_starter(callback, state):
        await callback.answer("Тільки той хто розпочав може закрити.", show_alert=True)
        return
    await _clear_prompt(bot, callback.message.chat.id, state)
    try:
        await bot.delete_message(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    ACTIVE_SESSIONS.pop(callback.message.chat.id, None)
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("rn_go_"))
async def cb_start(callback: CallbackQuery, state: FSMContext) -> None:
    sid = callback.data.split("_", 2)[2]
    if not _check_session(callback, sid):
        await callback.answer("Цей запис вже завершено.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    is_private = callback.message.chat.type == "private"

    if is_private:
        group_id = await _admin_primary_group(callback.from_user.username)
        if group_id is None:
            await callback.answer("Ваш акаунт не знайдено.", show_alert=True)
            return
    else:
        group = await _find_group_by_chat(chat_id)
        if not group:
            await callback.answer("Чат не привʼязаний до групи.", show_alert=True)
            return
        group_id = group["id"]

    try:
        cabinet = await api_client.get_cabinet(group_id)
    except Exception:
        logger.exception("Failed to fetch cabinet")
        await callback.answer("Помилка завантаження.", show_alert=True)
        return

    meeting_date = cabinet.get("prevScheduledMeetingDate") or cabinet.get("lastMeetingDate") or _today_iso()

    try:
        candidates, has_attendance = await _build_candidates(group_id, meeting_date)
    except Exception:
        logger.exception("Failed to build candidates")
        await callback.answer("Помилка завантаження.", show_alert=True)
        return

    if not candidates:
        await callback.answer("У домашці немає членів.", show_alert=True)
        return

    ACTIVE_SESSIONS[chat_id] = {"sid": sid, "msg_id": callback.message.message_id, "user_id": callback.from_user.id}

    await state.update_data(
        sid=sid,
        group_id=group_id,
        meeting_date=meeting_date,
        candidates=candidates,
        recorded=[],
        starter_user_id=callback.from_user.id,
        msg_id=callback.message.message_id,
        chat_id=chat_id,
        is_private=is_private,
        has_attendance=has_attendance,
    )

    await callback.message.edit_text(
        _picker_text(meeting_date, has_attendance),
        parse_mode="HTML",
        reply_markup=_picker_kb(sid, candidates, set()),
    )
    await callback.answer()


# ── Pick member / guest / back / done ──────────────────────────────────────────

@router.callback_query(F.data.startswith("rn_pk_"))
async def cb_pick(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    parts = callback.data.split("_")
    # rn_pk_{sid}_{tc}_{id}
    sid, tc, mid = parts[2], parts[3], int(parts[4])
    if not _check_session(callback, sid):
        await callback.answer("Цей запис вже завершено.", show_alert=True)
        return
    if not await _check_starter(callback, state):
        await callback.answer("Тільки той хто розпочав запис може додавати потреби.", show_alert=True)
        return

    data = await state.get_data()
    candidate = next(
        (c for c in data.get("candidates", []) if c["tc"] == tc and c["id"] == mid),
        None,
    )
    if candidate is None:
        await callback.answer("Невідомий учасник.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    await _clear_prompt(bot, chat_id, state)

    name = candidate["name"]
    prompt = await bot.send_message(
        chat_id,
        f"Введіть потребу для {name}:",
        reply_markup=_force_reply("Текст потреби…"),
    )
    await state.set_state(RecordNeedsStates.waiting_need_text)
    await state.update_data(
        current_pick={
            "tc": tc, "id": mid, "name": name,
            "telegram": candidate.get("telegram") or "",
        },
        prompt_msg_id=prompt.message_id,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rn_gu_"))
async def cb_guest(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    sid = callback.data.split("_", 2)[2]
    if not _check_session(callback, sid):
        await callback.answer("Цей запис вже завершено.", show_alert=True)
        return
    if not await _check_starter(callback, state):
        await callback.answer("Тільки той хто розпочав запис може додавати потреби.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    await _clear_prompt(bot, chat_id, state)

    prompt = await bot.send_message(
        chat_id, "Введіть імʼя гостя:",
        reply_markup=_force_reply("Імʼя гостя…"),
    )
    await state.set_state(RecordNeedsStates.waiting_guest_name)
    await state.update_data(prompt_msg_id=prompt.message_id)
    await callback.answer()


@router.message(RecordNeedsStates.waiting_guest_name)
async def receive_guest_name(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if message.from_user.id != data.get("starter_user_id"):
        return
    chat_id = data.get("chat_id") or message.chat.id

    await _clear_prompt(bot, chat_id, state)
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    name = (message.text or "").strip()
    if not name:
        return

    prompt = await bot.send_message(
        chat_id, f"Введіть потребу для {name}:",
        reply_markup=_force_reply("Текст потреби…"),
    )
    await state.set_state(RecordNeedsStates.waiting_need_text)
    await state.update_data(
        current_pick={"tc": "g", "id": None, "name": name, "telegram": ""},
        prompt_msg_id=prompt.message_id,
    )


@router.message(RecordNeedsStates.waiting_need_text)
async def receive_need_text(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if message.from_user.id != data.get("starter_user_id"):
        return
    msg_id = data.get("msg_id")
    chat_id = data.get("chat_id") or message.chat.id
    sid = data.get("sid")
    group_id = data.get("group_id")
    current = data.get("current_pick")
    candidates = data.get("candidates", [])
    has_attendance = bool(data.get("has_attendance", True))
    meeting_date = data.get("meeting_date")

    await _clear_prompt(bot, chat_id, state)
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    text = (message.text or "").strip()
    if not text or not current or not msg_id:
        return

    try:
        await api_client.create_need(group_id, {
            "subjectName": current["name"],
            "description": text,
            "personId": current["id"] if current["tc"] == "p" else None,
            "userId": current["id"] if current["tc"] == "u" else None,
        })
    except Exception:
        logger.exception("Failed to create need")
        return

    recorded = list(data.get("recorded", []))
    recorded.append({
        "tc": current["tc"],
        "id": current["id"],
        "name": current["name"],
        "telegram": current.get("telegram") or "",
        "description": text,
    })

    await state.set_state(state=None)
    await state.update_data(recorded=recorded, current_pick=None)

    recorded_keys = {(r["tc"], r["id"]) for r in recorded if r["tc"] in ("p", "u")}
    await bot.edit_message_text(
        chat_id=chat_id, message_id=msg_id,
        text=_picker_text(meeting_date, has_attendance),
        parse_mode="HTML",
        reply_markup=_picker_kb(sid, candidates, recorded_keys),
    )


@router.callback_query(F.data.startswith("rn_dn_"))
async def cb_done(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    sid = callback.data.split("_", 2)[2]
    if not _check_session(callback, sid):
        await callback.answer("Цей запис вже завершено.", show_alert=True)
        return
    if not await _check_starter(callback, state):
        await callback.answer("Тільки той хто розпочав запис.", show_alert=True)
        return

    data = await state.get_data()
    meeting_date = data.get("meeting_date")
    recorded = data.get("recorded", [])

    await _clear_prompt(bot, callback.message.chat.id, state)

    report_text = _build_report(meeting_date, recorded)
    await callback.message.edit_text(
        report_text, parse_mode="HTML", disable_web_page_preview=True
    )

    ACTIVE_SESSIONS.pop(callback.message.chat.id, None)
    await state.clear()
    await callback.answer("Готово")


# ── Report ─────────────────────────────────────────────────────────────────────

def _build_report(meeting_date: str | None, recorded: list[dict]) -> str:
    header = f"📝 <b>Потреби домашки {_fmt_date_uk(meeting_date)}</b>"
    if not recorded:
        return f"{header}\n\nПотреби не записано"

    grouped_descs: dict[tuple[str, str, int | None], list[str]] = {}
    telegrams: dict[tuple[str, str, int | None], str] = {}
    order: list[tuple[str, str, int | None]] = []
    for r in recorded:
        key = (r["tc"], r["name"], r["id"])
        if key not in grouped_descs:
            grouped_descs[key] = []
            telegrams[key] = r.get("telegram") or ""
            order.append(key)
        grouped_descs[key].append(r["description"])

    lines = [header, ""]
    for key in order:
        tc, name, _ = key
        descs = "; ".join(grouped_descs[key])
        if tc == "g":
            label = f"{html.escape(name)} (гість)"
        else:
            tg = telegrams[key].lstrip("@").strip()
            if tg:
                url = f"https://t.me/{tg}"
                label = f'<a href="{html.escape(url)}">{html.escape(name)}</a>'
            else:
                label = html.escape(name)
        lines.append(f"• {label} — {html.escape(descs)}")

    return "\n".join(lines)
