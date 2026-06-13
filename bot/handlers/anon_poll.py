"""Anonymous poll — admin starts a window during which members can write
to the bot in private; bot forwards each message anonymously to the
destination chat (the leader group chat OR admin's private chat).

Entry points:
- /anon_poll slash command in leader group chat → destination = group chat
- "Анонімне опитування" inline button in Домашка private menu → destination = admin's private chat

Active polls live in DB (auto-expire at end of Kyiv day). Bot forwards
any plain text message from recognised non-admin Person whose primaryGroup
has an active poll.
"""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_client import api_client
from bot.utils import find_admin_by_telegram, find_person_by_telegram

router = Router()
logger = logging.getLogger(__name__)


CONFIRM_TEXT = (
    "<b>Запустити анонімний збір повідомлень?</b>\n\n"
    "Члени домашки зможуть писати боту в приват — повідомлення передаватимуться "
    "сюди анонімно до кінця дня."
)

NOTIF_TO_MEMBER = (
    "🤫 <b>Запущено анонімний збір повідомлень</b>\n\n"
    "Можете написати сюди повідомлення чи питання — їх буде передано анонімно "
    "лідерам вашої домашки. Збір триватиме до кінця дня."
)


# ── Confirmation prompt ───────────────────────────────────────────────────────

def _confirm_kb(group_id: int, dest_chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Скасувати", callback_data="ap_cancel"),
            InlineKeyboardButton(text="Запустити", callback_data=f"ap_go_{group_id}_{dest_chat_id}"),
        ],
    ])


async def _find_group_by_chat(chat_id: int) -> dict | None:
    groups = await api_client.get_groups()
    return next((g for g in groups if g.get("telegramGroupId") == str(chat_id)), None)


# ── /anon_poll in group chat ──────────────────────────────────────────────────

@router.message(Command("anon_poll"))
async def cmd_anon_poll(message: Message, bot: Bot) -> None:
    if message.chat.type == "private":
        await message.answer("Ця команда працює тільки в груповому чаті лідерів.")
        return

    group = await _find_group_by_chat(message.chat.id)
    if not group:
        await message.answer("Цей чат не привʼязаний до домашки в CRM.")
        return

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    await message.answer(
        CONFIRM_TEXT,
        parse_mode="HTML",
        reply_markup=_confirm_kb(group["id"], message.chat.id),
    )


# ── "Анонімне опитування" inline button from Домашка ──────────────────────────

@router.callback_query(F.data == "hg_anon_poll")
async def cb_anon_poll_private(callback: CallbackQuery) -> None:
    if callback.message.chat.type != "private":
        return
    username = callback.from_user.username or ""
    admin = await find_admin_by_telegram(username)
    if admin is None:
        await callback.answer("Ваш акаунт не знайдено в CRM.", show_alert=True)
        return
    group_id = admin.get("primaryGroupId")
    if not group_id:
        await callback.answer("У вас не вказана основна група.", show_alert=True)
        return

    await callback.message.edit_text(
        CONFIRM_TEXT,
        parse_mode="HTML",
        reply_markup=_confirm_kb(group_id, callback.message.chat.id),
    )
    await callback.answer()


# ── Confirmation handlers ─────────────────────────────────────────────────────

@router.callback_query(F.data == "ap_cancel")
async def cb_cancel(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await bot.delete_message(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ap_go_"))
async def cb_start(callback: CallbackQuery, bot: Bot) -> None:
    parts = callback.data.split("_")
    # ap_go_{group_id}_{dest_chat_id}
    group_id = int(parts[2])
    dest_chat_id = int(parts[3])

    try:
        poll = await api_client.create_anon_poll(group_id, dest_chat_id)
    except Exception:
        logger.exception("Failed to create anon poll")
        await callback.answer("Не вдалося запустити збір. Спробуйте ще раз.", show_alert=True)
        return

    await callback.message.edit_text(
        "✅ <b>Анонімний збір запущено</b>\n\n"
        "Повідомлення членів домашки приходитимуть сюди до кінця дня.",
        parse_mode="HTML",
    )
    await callback.answer()

    asyncio.create_task(_notify_members(bot, group_id))


async def _notify_members(bot: Bot, group_id: int) -> None:
    """Send NOTIF_TO_MEMBER to every Person in the group with a known TelegramChatId."""
    try:
        members = await api_client.get_group_members(group_id)
    except Exception:
        logger.exception("anon poll: failed to fetch members for group %s", group_id)
        return

    for m in members:
        if m.get("isAdmin") or m.get("isFormer"):
            continue
        chat_id = m.get("telegramChatId")
        if not chat_id:
            continue
        try:
            await bot.send_message(int(chat_id), NOTIF_TO_MEMBER, parse_mode="HTML")
        except Exception:
            logger.warning("anon poll: failed to notify chat %s", chat_id)


# ── Forward member messages while a poll is active ─────────────────────────────

@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def forward_anon_message(message: Message, bot: Bot) -> None:
    """Catch-all (registered last). Forwards plain text from non-admin members to active poll."""
    username = message.from_user.username if message.from_user else None
    if not username:
        return

    # Don't forward admin messages — they have their own menu.
    admin = await find_admin_by_telegram(username)
    if admin is not None:
        return

    person = await find_person_by_telegram(username)
    if person is None:
        return

    group_id = person.get("primaryGroupId")
    if not group_id:
        return

    try:
        poll = await api_client.get_active_anon_poll(group_id)
    except Exception:
        logger.exception("anon poll: failed to check active poll")
        return

    if not poll:
        return

    dest = poll.get("destinationChatId")
    if not dest:
        return

    text = message.text or ""
    try:
        await bot.send_message(
            int(dest),
            f"📩 <b>Анонімне:</b>\n{html.escape(text)}",
            parse_mode="HTML",
        )
        await message.reply("✓ Передано анонімно")
    except Exception:
        logger.exception("anon poll: forward failed")
