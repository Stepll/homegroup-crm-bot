import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.api_client import api_client
from bot.handlers.attendance import start_attendance_flow
from bot.utils import find_admin_by_telegram

router = Router()
router.message.filter(F.chat.type == "private")

logger = logging.getLogger(__name__)


async def _get_admin_group(message: Message) -> tuple[dict, int] | None:
    """Returns (admin, group_id) or sends an error and returns None."""
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


@router.message(F.text == "Відмітка присутніх")
async def btn_attendance(message: Message, bot: Bot) -> None:
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result

    cabinet = await api_client.get_cabinet(group_id)
    meeting_date = cabinet.get("prevScheduledMeetingDate") or cabinet.get("lastMeetingDate")
    if not meeting_date:
        await message.answer("Немає дати зустрічі для вашої групи.")
        return

    await start_attendance_flow(bot, group_id, str(message.chat.id), meeting_date)





