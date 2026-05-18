import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.api_client import api_client
from bot.handlers.plans import build_telegram_map, format_plan
from bot.utils import find_admin_by_telegram


def _fmt_date(date: str) -> str:
    try:
        y, m, d = date.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return date

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    """Returns (plan, next_date). plan is None if no plan exists."""
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


def _no_plan_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Створити план", callback_data=f"pp_create_{group_id}"),
            InlineKeyboardButton(text="З шаблону", callback_data=f"pp_template_{group_id}"),
        ],
    ])


def _has_plan_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Змінити план", callback_data=f"pp_edit_{group_id}"),
            InlineKeyboardButton(text="Очистити план", callback_data=f"pp_clear_{group_id}"),
        ],
        [InlineKeyboardButton(text="Відправити в групу", callback_data=f"pp_send_{group_id}")],
    ])


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
        await message.answer(
            f"Плану на {_fmt_date(next_date)} ще немає.",
            reply_markup=_no_plan_kb(group_id),
        )
        return

    text = await _plan_text(plan, next_date)
    await message.answer(text, reply_markup=_has_plan_kb(group_id))


@router.callback_query(F.data.startswith("pp_reload_"))
async def cb_reload(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split("_")[2])
    plan, next_date = await _load_plan_data(group_id)

    if next_date is None:
        await callback.message.edit_text("Немає запланованих зустрічей для вашої групи.")
        await callback.answer()
        return

    if plan is None:
        await callback.message.edit_text(
            f"Плану на {_fmt_date(next_date)} ще немає.",
            reply_markup=_no_plan_kb(group_id),
        )
        await callback.answer()
        return

    text = await _plan_text(plan, next_date)
    await callback.message.edit_text(text, reply_markup=_has_plan_kb(group_id))
    await callback.answer()


# ── Stubs ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pp_create_"))
async def cb_create(callback: CallbackQuery) -> None:
    await callback.answer("Незабаром...", show_alert=True)


@router.callback_query(F.data.startswith("pp_template_"))
async def cb_template(callback: CallbackQuery) -> None:
    await callback.answer("Незабаром...", show_alert=True)


@router.callback_query(F.data.startswith("pp_edit_"))
async def cb_edit(callback: CallbackQuery) -> None:
    await callback.answer("Незабаром...", show_alert=True)


@router.callback_query(F.data.startswith("pp_clear_"))
async def cb_clear(callback: CallbackQuery) -> None:
    await callback.answer("Незабаром...", show_alert=True)


@router.callback_query(F.data.startswith("pp_send_"))
async def cb_send(callback: CallbackQuery) -> None:
    await callback.answer("Незабаром...", show_alert=True)
