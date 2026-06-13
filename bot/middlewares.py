"""Aiogram middlewares."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.api_client import api_client
from bot.utils import find_admin_by_telegram, find_person_by_telegram

logger = logging.getLogger(__name__)

# In-memory cache: username (lower) → last-seen chat_id we synced
_SYNCED_CHAT_IDS: dict[str, int] = {}


async def _sync_chat_id(username: str, chat_id: int) -> None:
    """Look up admin/person by username, persist their chat_id in CRM if needed."""
    try:
        admin = await find_admin_by_telegram(username)
        if admin is not None:
            if admin.get("telegramChatId") != chat_id:
                await api_client.set_admin_telegram_chat_id(admin["id"], chat_id)
            return
        person = await find_person_by_telegram(username)
        if person is not None:
            if person.get("telegramChatId") != chat_id:
                await api_client.set_person_telegram_chat_id(person["id"], chat_id)
    except Exception:
        logger.exception("Failed to sync chat_id for @%s", username)


class TelegramChatIdMiddleware(BaseMiddleware):
    """On every private-chat message, persist the user's chat_id in CRM (if recognised).

    Runs in the background — doesn't block handler execution. Uses an in-memory cache
    to avoid repeating the API write on every subsequent message in the same session.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type == "private" and event.from_user:
            username = event.from_user.username
            chat_id = event.chat.id
            if username:
                key = username.lower()
                if _SYNCED_CHAT_IDS.get(key) != chat_id:
                    _SYNCED_CHAT_IDS[key] = chat_id
                    asyncio.create_task(_sync_chat_id(username, chat_id))
        return await handler(event, data)
