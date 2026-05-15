from aiogram import Bot, Router
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import ChatMemberUpdated

router = Router()


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def bot_added_to_group(event: ChatMemberUpdated, bot: Bot) -> None:
    await bot.send_message(
        event.chat.id,
        f"Привіт! Я бот HomeGroup CRM 👋\n\n"
        f"ID цієї групи: <code>{event.chat.id}</code>\n\n"
        f"Скопіюй цей ID і вкажи його в налаштуваннях домашньої групи в CRM (поле Telegram Group ID).",
        parse_mode="HTML",
    )
