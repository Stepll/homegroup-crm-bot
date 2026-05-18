import html
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.api_client import api_client
from bot.handlers.plans import build_telegram_map, format_plan
from bot.utils import find_admin_by_telegram

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

logger = logging.getLogger(__name__)


class PlanEditStates(StatesGroup):
    add_time = State()
    add_title = State()
    add_info = State()
    add_resp = State()
    edit_time = State()
    edit_title = State()
    edit_info = State()
    edit_resp = State()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_date(date: str) -> str:
    try:
        y, m, d = date.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return date


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


async def _load_plan_data(group_id: int) -> tuple[dict | None, str | None]:
    cabinet = await api_client.get_cabinet(group_id)
    next_date = cabinet.get("nextMeetingDate")
    if not next_date:
        return None, None
    plan = await api_client.get_plan(group_id, next_date)
    return plan, next_date


async def _plan_text(plan: dict, next_date: str) -> str:
    people, admins = await api_client.get_people(), await api_client.get_admins()
    tg_map = build_telegram_map(people, admins)
    return format_plan(plan, next_date, tg_map)


async def _save_plan(group_id: int, date: str, blocks: list) -> dict:
    payload_blocks = [
        {
            "order": b.get("order", 9999),
            "time": b.get("time") or "",
            "title": b.get("title") or "",
            "info": b.get("info") or None,
            "responsible": b.get("responsible") or None,
        }
        for b in sorted(blocks, key=lambda x: x.get("order", 9999))
    ]
    return await api_client.save_plan(group_id, {"meetingDate": date, "blocks": payload_blocks})


async def _get_group_admins(group_id: int) -> list:
    members = await api_client.get_group_members(group_id)
    return [m for m in members if m.get("isAdmin")]


async def _delete_msg(bot: Bot, chat_id: int, msg_id: int) -> None:
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _no_plan_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Створити план", callback_data=f"pp_create_{group_id}"),
        InlineKeyboardButton(text="З шаблону", callback_data=f"pp_template_{group_id}"),
    ]])


def _has_plan_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Змінити план", callback_data=f"pp_edit_{group_id}"),
            InlineKeyboardButton(text="Очистити план", callback_data=f"pp_clear_{group_id}"),
        ],
        [InlineKeyboardButton(text="Відправити в групу", callback_data=f"pp_send_{group_id}")],
    ])


def _edit_list_kb(plan: dict, group_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Додати блок", callback_data=f"pp_badd_{group_id}")]]
    for block in sorted(plan.get("blocks") or [], key=lambda b: b.get("order", 0)):
        order = block["order"]
        time_str = (block.get("time") or "").strip()
        title = (block.get("title") or "").strip()
        resp = (block.get("responsible") or "").strip()
        label = f"{time_str + ' — ' if time_str else ''}{title}"
        if resp:
            label += f" ({resp})"
        rows.append([InlineKeyboardButton(text=label[:48], callback_data=f"pp_eblk_{group_id}_{order}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"pp_reload_{group_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _block_card_text(block: dict) -> str:
    time_str = block.get("time") or "—"
    title = html.escape(block.get("title") or "—")
    info = html.escape(block.get("info") or "—")
    resp = html.escape(block.get("responsible") or "—")
    return (
        f"<b>Блок {block.get('order', '?')}</b>\n\n"
        f"Час: {time_str}\n"
        f"Назва: {title}\n"
        f"Опис: {info}\n"
        f"Відповідальний: {resp}"
    )


def _block_card_kb(group_id: int, order: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Час", callback_data=f"pp_btime_{group_id}_{order}"),
            InlineKeyboardButton(text="Назва", callback_data=f"pp_btitle_{group_id}_{order}"),
        ],
        [
            InlineKeyboardButton(text="Опис", callback_data=f"pp_binfo_{group_id}_{order}"),
            InlineKeyboardButton(text="Відповідальний", callback_data=f"pp_bresp_{group_id}_{order}"),
        ],
        [InlineKeyboardButton(text="🗑 Видалити блок", callback_data=f"pp_bdel_{group_id}_{order}")],
        [InlineKeyboardButton(text="← Назад", callback_data=f"pp_edit_{group_id}")],
    ])


async def _resp_kb(
    group_id: int, back_cb: str, skip_cb: str | None = None
) -> InlineKeyboardMarkup:
    admins = await _get_group_admins(group_id)
    rows = [
        [InlineKeyboardButton(
            text=f"{a.get('name', '')} {a.get('lastName') or ''}".strip(),
            callback_data=f"pp_respsel_{a.get('userId') or a.get('id')}",
        )]
        for a in admins
    ]
    bottom = []
    if skip_cb:
        bottom.append(InlineKeyboardButton(text="Пропустити", callback_data=skip_cb))
    bottom.append(InlineKeyboardButton(text="← Назад", callback_data=back_cb))
    rows.append(bottom)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _skip_cancel_kb(cancel_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустити", callback_data="pp_addskip"),
        InlineKeyboardButton(text="Скасувати", callback_data=cancel_cb),
    ]])


def _cancel_kb_inline(cancel_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Скасувати", callback_data=cancel_cb),
    ]])


# ── Entry point ───────────────────────────────────────────────────────────────

@router.message(F.text == "План")
async def btn_plan(message: Message, state: FSMContext) -> None:
    await state.clear()
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result
    plan, next_date = await _load_plan_data(group_id)

    if next_date is None:
        await message.answer("Немає запланованих зустрічей для вашої групи.")
        return
    if plan is None:
        await message.answer(f"Плану на {_fmt_date(next_date)} ще немає.", reply_markup=_no_plan_kb(group_id))
        return
    await message.answer(await _plan_text(plan, next_date), reply_markup=_has_plan_kb(group_id))


@router.callback_query(F.data.startswith("pp_reload_"))
async def cb_reload(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    plan, next_date = await _load_plan_data(group_id)

    if next_date is None:
        await callback.message.edit_text("Немає запланованих зустрічей для вашої групи.")
    elif plan is None:
        await callback.message.edit_text(f"Плану на {_fmt_date(next_date)} ще немає.", reply_markup=_no_plan_kb(group_id))
    else:
        await callback.message.edit_text(await _plan_text(plan, next_date), reply_markup=_has_plan_kb(group_id))
    await callback.answer()


# ── Edit list ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_edit_"))
async def cb_edit_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    plan, next_date = await _load_plan_data(group_id)
    if not next_date:
        await callback.answer("Немає дати зустрічі.", show_alert=True)
        return
    if plan is None:
        plan = {"blocks": []}
    await callback.message.edit_text(
        f"<b>Редагування плану на {_fmt_date(next_date)}</b>",
        parse_mode="HTML",
        reply_markup=_edit_list_kb(plan, group_id),
    )
    await callback.answer()


# ── Block card ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_eblk_"))
async def cb_block_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    plan, _ = await _load_plan_data(group_id)
    block = next((b for b in (plan.get("blocks") or []) if b["order"] == order), None) if plan else None
    if not block:
        await callback.answer("Блок не знайдено.", show_alert=True)
        return
    await callback.message.edit_text(_block_card_text(block), parse_mode="HTML", reply_markup=_block_card_kb(group_id, order))
    await callback.answer()


# ── Delete block ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_bdel_"))
async def cb_bdel_confirm(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Так, видалити", callback_data=f"pp_bdelok_{group_id}_{order}"),
        InlineKeyboardButton(text="Скасувати", callback_data=f"pp_eblk_{group_id}_{order}"),
    ]]))
    await callback.answer()


@router.callback_query(F.data.startswith("pp_bdelok_"))
async def cb_bdel_ok(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    plan, next_date = await _load_plan_data(group_id)
    if not plan or not next_date:
        await callback.answer("Плану не знайдено.", show_alert=True)
        return
    blocks = [b for b in (plan.get("blocks") or []) if b["order"] != order]
    try:
        saved = await _save_plan(group_id, next_date, blocks)
    except Exception:
        logger.exception("Failed to delete block")
        await callback.answer("Помилка видалення.", show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>Редагування плану на {_fmt_date(next_date)}</b>",
        parse_mode="HTML",
        reply_markup=_edit_list_kb(saved, group_id),
    )
    await callback.answer("Блок видалено")


# ── Edit field callbacks (enter FSM, edit message in-place) ───────────────────

@router.callback_query(F.data.startswith("pp_btime_"))
async def cb_btime(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    await state.set_state(PlanEditStates.edit_time)
    await state.update_data(gid=group_id, order=order, msg_id=callback.message.message_id)
    await callback.message.edit_text(
        'Введіть новий час (наприклад 19:00)\nабо "-" щоб прибрати:',
        reply_markup=_cancel_kb_inline(f"pp_eblk_{group_id}_{order}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pp_btitle_"))
async def cb_btitle(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    await state.set_state(PlanEditStates.edit_title)
    await state.update_data(gid=group_id, order=order, msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "Введіть нову назву блоку:",
        reply_markup=_cancel_kb_inline(f"pp_eblk_{group_id}_{order}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pp_binfo_"))
async def cb_binfo(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    await state.set_state(PlanEditStates.edit_info)
    await state.update_data(gid=group_id, order=order, msg_id=callback.message.message_id)
    await callback.message.edit_text(
        'Введіть опис блоку\nабо "-" щоб прибрати:',
        reply_markup=_cancel_kb_inline(f"pp_eblk_{group_id}_{order}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pp_bresp_"))
async def cb_bresp(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split("_")
    group_id, order = int(parts[2]), int(parts[3])
    await state.set_state(PlanEditStates.edit_resp)
    await state.update_data(gid=group_id, order=order, msg_id=callback.message.message_id)
    kb = await _resp_kb(group_id, back_cb=f"pp_eblk_{group_id}_{order}")
    await callback.message.edit_text(
        "Оберіть відповідального або напишіть ім'я\n(\"-\" щоб прибрати):",
        reply_markup=kb,
    )
    await callback.answer()


# ── Edit field text input (delete user msg, edit original) ────────────────────

@router.message(PlanEditStates.edit_time)
async def recv_edit_time(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    text = (message.text or "").strip()
    await _delete_msg(bot, message.chat.id, message.message_id)
    await _patch_via_bot(bot, message.chat.id, data["msg_id"], data["gid"], data["order"],
                         {"time": None if text == "-" else text or None})


@router.message(PlanEditStates.edit_title)
async def recv_edit_title(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    title = (message.text or "").strip()
    if not title:
        await _delete_msg(bot, message.chat.id, message.message_id)
        await bot.edit_message_text(
            "Назва не може бути порожньою. Введіть назву блоку:",
            chat_id=message.chat.id, message_id=data["msg_id"],
            reply_markup=_cancel_kb_inline(f"pp_eblk_{data['gid']}_{data['order']}"),
        )
        return
    await state.clear()
    await _delete_msg(bot, message.chat.id, message.message_id)
    await _patch_via_bot(bot, message.chat.id, data["msg_id"], data["gid"], data["order"], {"title": title})


@router.message(PlanEditStates.edit_info)
async def recv_edit_info(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    text = (message.text or "").strip()
    await _delete_msg(bot, message.chat.id, message.message_id)
    await _patch_via_bot(bot, message.chat.id, data["msg_id"], data["gid"], data["order"],
                         {"info": None if text == "-" else text or None})


@router.message(PlanEditStates.edit_resp)
async def recv_edit_resp(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    text = (message.text or "").strip()
    await _delete_msg(bot, message.chat.id, message.message_id)
    await _patch_via_bot(bot, message.chat.id, data["msg_id"], data["gid"], data["order"],
                         {"responsible": None if text == "-" else text or None})


@router.callback_query(PlanEditStates.edit_resp, F.data.startswith("pp_respsel_"))
async def cb_respsel_edit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    uid = int(callback.data.split("_")[2])
    admin = await api_client.get_admin(uid)
    name = f"{admin.get('name', '')} {admin.get('lastName') or ''}".strip()
    await _patch_and_show_cb(callback, data["gid"], data["order"], {"responsible": name or None})


# ── Add block ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_badd_"))
async def cb_badd(callback: CallbackQuery, state: FSMContext) -> None:
    group_id = int(callback.data.split("_")[2])
    _, next_date = await _load_plan_data(group_id)
    if not next_date:
        await callback.answer("Немає дати зустрічі.", show_alert=True)
        return
    await state.set_state(PlanEditStates.add_time)
    await state.update_data(gid=group_id, next_date=next_date, msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "Введіть час блоку (наприклад 19:00):",
        reply_markup=_skip_cancel_kb(f"pp_edit_{group_id}"),
    )
    await callback.answer()


# add_time
@router.message(PlanEditStates.add_time)
async def recv_add_time(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.update_data(time=(message.text or "").strip() or None)
    await state.set_state(PlanEditStates.add_title)
    await _delete_msg(bot, message.chat.id, message.message_id)
    await bot.edit_message_text(
        "Введіть назву блоку:",
        chat_id=message.chat.id, message_id=data["msg_id"],
        reply_markup=_cancel_kb_inline(f"pp_edit_{data['gid']}"),
    )


@router.callback_query(PlanEditStates.add_time, F.data == "pp_addskip")
async def cb_skip_time(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(time=None)
    await state.set_state(PlanEditStates.add_title)
    await callback.message.edit_text("Введіть назву блоку:", reply_markup=_cancel_kb_inline(f"pp_edit_{data['gid']}"))
    await callback.answer()


# add_title
@router.message(PlanEditStates.add_title)
async def recv_add_title(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    title = (message.text or "").strip()
    await _delete_msg(bot, message.chat.id, message.message_id)
    if not title:
        await bot.edit_message_text(
            "Назва не може бути порожньою. Введіть назву блоку:",
            chat_id=message.chat.id, message_id=data["msg_id"],
            reply_markup=_cancel_kb_inline(f"pp_edit_{data['gid']}"),
        )
        return
    await state.update_data(title=title)
    await state.set_state(PlanEditStates.add_info)
    await bot.edit_message_text(
        "Введіть опис блоку:",
        chat_id=message.chat.id, message_id=data["msg_id"],
        reply_markup=_skip_cancel_kb(f"pp_edit_{data['gid']}"),
    )


# add_info
@router.message(PlanEditStates.add_info)
async def recv_add_info(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.update_data(info=(message.text or "").strip() or None)
    await state.set_state(PlanEditStates.add_resp)
    await _delete_msg(bot, message.chat.id, message.message_id)
    kb = await _resp_kb(data["gid"], back_cb=f"pp_edit_{data['gid']}", skip_cb="pp_addskip")
    await bot.edit_message_text(
        "Оберіть відповідального або напишіть ім'я:",
        chat_id=message.chat.id, message_id=data["msg_id"],
        reply_markup=kb,
    )


@router.callback_query(PlanEditStates.add_info, F.data == "pp_addskip")
async def cb_skip_info(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(info=None)
    await state.set_state(PlanEditStates.add_resp)
    kb = await _resp_kb(data["gid"], back_cb=f"pp_edit_{data['gid']}", skip_cb="pp_addskip")
    await callback.message.edit_text("Оберіть відповідального або напишіть ім'я:", reply_markup=kb)
    await callback.answer()


# add_resp
@router.callback_query(PlanEditStates.add_resp, F.data.startswith("pp_respsel_"))
async def cb_respsel_add(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    uid = int(callback.data.split("_")[2])
    admin = await api_client.get_admin(uid)
    name = f"{admin.get('name', '')} {admin.get('lastName') or ''}".strip()
    await state.update_data(resp=name or None)
    await _finish_add_cb(callback, state)


@router.message(PlanEditStates.add_resp)
async def recv_add_resp(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.update_data(resp=(message.text or "").strip() or None)
    await _delete_msg(bot, message.chat.id, message.message_id)
    await _finish_add_raw(bot, message.chat.id, data["msg_id"], state)


@router.callback_query(PlanEditStates.add_resp, F.data == "pp_addskip")
async def cb_skip_resp(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(resp=None)
    await _finish_add_cb(callback, state)


# ── Add block finish helpers ──────────────────────────────────────────────────

async def _finish_add_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    saved = await _do_add_block(data)
    if saved is None:
        await callback.answer("Помилка збереження.", show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>Редагування плану на {_fmt_date(data['next_date'])}</b>",
        parse_mode="HTML",
        reply_markup=_edit_list_kb(saved, data["gid"]),
    )
    await callback.answer()


async def _finish_add_raw(bot: Bot, chat_id: int, msg_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    saved = await _do_add_block(data)
    if saved is None:
        await bot.edit_message_text("Помилка збереження.", chat_id=chat_id, message_id=msg_id)
        return
    await bot.edit_message_text(
        f"<b>Редагування плану на {_fmt_date(data['next_date'])}</b>",
        chat_id=chat_id, message_id=msg_id,
        parse_mode="HTML",
        reply_markup=_edit_list_kb(saved, data["gid"]),
    )


async def _do_add_block(data: dict) -> dict | None:
    group_id, next_date = data["gid"], data["next_date"]
    plan = await api_client.get_plan(group_id, next_date)
    existing = list(plan.get("blocks") or []) if plan else []
    next_order = max((b["order"] for b in existing), default=0) + 1
    existing.append({
        "order": next_order,
        "time": data.get("time"),
        "title": data.get("title", ""),
        "info": data.get("info"),
        "responsible": data.get("resp"),
    })
    try:
        return await _save_plan(group_id, next_date, existing)
    except Exception:
        logger.exception("Failed to add block")
        return None


# ── Patch helpers ─────────────────────────────────────────────────────────────

async def _patch_via_bot(
    bot: Bot, chat_id: int, msg_id: int, group_id: int, order: int, patch: dict
) -> None:
    plan, next_date = await _load_plan_data(group_id)
    if not plan or not next_date:
        await bot.edit_message_text("Плану не знайдено.", chat_id=chat_id, message_id=msg_id)
        return
    blocks = plan.get("blocks") or []
    block = next((b for b in blocks if b["order"] == order), None)
    if not block:
        await bot.edit_message_text("Блок не знайдено.", chat_id=chat_id, message_id=msg_id)
        return
    block.update(patch)
    try:
        saved = await _save_plan(group_id, next_date, blocks)
    except Exception:
        logger.exception("Failed to patch block")
        await bot.edit_message_text("Помилка збереження.", chat_id=chat_id, message_id=msg_id)
        return
    updated = next((b for b in (saved.get("blocks") or []) if b["order"] == order), block)
    await bot.edit_message_text(
        _block_card_text(updated), chat_id=chat_id, message_id=msg_id,
        parse_mode="HTML", reply_markup=_block_card_kb(group_id, order),
    )


async def _patch_and_show_cb(
    callback: CallbackQuery, group_id: int, order: int, patch: dict
) -> None:
    plan, next_date = await _load_plan_data(group_id)
    if not plan or not next_date:
        await callback.answer("Плану не знайдено.", show_alert=True)
        return
    blocks = plan.get("blocks") or []
    block = next((b for b in blocks if b["order"] == order), None)
    if not block:
        await callback.answer("Блок не знайдено.", show_alert=True)
        return
    block.update(patch)
    try:
        saved = await _save_plan(group_id, next_date, blocks)
    except Exception:
        logger.exception("Failed to patch block")
        await callback.answer("Помилка збереження.", show_alert=True)
        return
    updated = next((b for b in (saved.get("blocks") or []) if b["order"] == order), block)
    await callback.message.edit_text(
        _block_card_text(updated), parse_mode="HTML", reply_markup=_block_card_kb(group_id, order)
    )
    await callback.answer("Збережено")


# ── Create plan (→ edit list) ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_create_"))
async def cb_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    plan, next_date = await _load_plan_data(group_id)
    if not next_date:
        await callback.answer("Немає дати зустрічі.", show_alert=True)
        return
    if plan is None:
        plan = {"blocks": []}
    await callback.message.edit_text(
        f"<b>Редагування плану на {_fmt_date(next_date)}</b>",
        parse_mode="HTML",
        reply_markup=_edit_list_kb(plan, group_id),
    )
    await callback.answer()


# ── From template ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_template_"))
async def cb_template(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    templates = await api_client.get_plan_templates()
    if not templates:
        await callback.answer("Шаблонів немає.", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(
            text=html.escape(t["name"]),
            callback_data=f"pp_tmpl_{group_id}_{t['id']}",
        )]
        for t in templates
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"pp_reload_{group_id}")])
    await callback.message.edit_text(
        "<b>Оберіть шаблон:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pp_tmpl_"))
async def cb_apply_template(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    group_id, template_id = int(parts[2]), int(parts[3])
    _, next_date = await _load_plan_data(group_id)
    if not next_date:
        await callback.answer("Немає дати зустрічі.", show_alert=True)
        return
    templates = await api_client.get_plan_templates()
    tmpl = next((t for t in templates if t["id"] == template_id), None)
    if not tmpl:
        await callback.answer("Шаблон не знайдено.", show_alert=True)
        return
    blocks = [
        {
            "order": b["order"],
            "time": b.get("time") or None,
            "title": b.get("title") or "",
            "info": b.get("info") or None,
            "responsible": b.get("responsible") or None,
        }
        for b in sorted(tmpl.get("blocks") or [], key=lambda x: x.get("order", 0))
    ]
    try:
        saved = await _save_plan(group_id, next_date, blocks)
    except Exception:
        logger.exception("Failed to apply template")
        await callback.answer("Помилка застосування шаблону.", show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>Редагування плану на {_fmt_date(next_date)}</b>",
        parse_mode="HTML",
        reply_markup=_edit_list_kb(saved, group_id),
    )
    await callback.answer("Шаблон застосовано ✓")


# ── Clear plan ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_clear_"))
async def cb_clear(callback: CallbackQuery) -> None:
    group_id = int(callback.data.split("_")[2])
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Так, видалити", callback_data=f"pp_clearok_{group_id}"),
        InlineKeyboardButton(text="Скасувати", callback_data=f"pp_reload_{group_id}"),
    ]]))
    await callback.answer()


@router.callback_query(F.data.startswith("pp_clearok_"))
async def cb_clearok(callback: CallbackQuery) -> None:
    group_id = int(callback.data.split("_")[2])
    _, next_date = await _load_plan_data(group_id)
    if not next_date:
        await callback.answer("Немає дати зустрічі.", show_alert=True)
        return
    try:
        await api_client.delete_plan(group_id, next_date)
    except Exception:
        logger.exception("Failed to delete plan")
        await callback.answer("Помилка видалення.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Плану на {_fmt_date(next_date)} ще немає.",
        reply_markup=_no_plan_kb(group_id),
    )
    await callback.answer("План видалено")


# ── Send to Telegram group ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_send_"))
async def cb_send(callback: CallbackQuery) -> None:
    group_id = int(callback.data.split("_")[2])
    _, next_date = await _load_plan_data(group_id)
    if not next_date:
        await callback.answer("Немає дати зустрічі.", show_alert=True)
        return
    try:
        await api_client.send_plan_to_telegram(group_id, next_date)
    except Exception:
        logger.exception("Failed to send plan to Telegram")
        await callback.answer("Помилка відправки.", show_alert=True)
        return
    await callback.answer("План відправлено в групу ✓", show_alert=True)
