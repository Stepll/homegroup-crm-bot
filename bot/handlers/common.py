import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.api_client import api_client
from bot.keyboards import private_main_keyboard
from bot.schedulers.notifications import check_conflicts, notify_upcoming_events

router = Router()
logger = logging.getLogger(__name__)

GROUP_START_TEXT = (
    "Вітаю! Я бот HomeGroup CRM.\n\n"
    "Команди:\n"
    "/plan — план наступної зустрічі\n"
    "/attendance — відмітити присутніх\n"
    "/stats — статистика відвідуваності\n\n"
    "Автоматичні сповіщення:\n"
    "• Через годину після початку зустрічі — запит на відмітку присутніх\n"
    "• Щодня о 09:00 — події групи сьогодні та через 7 днів\n"
    "• Щодня о 09:00 — попередження якщо зустріч перетинається з іншими подіями"
)

PRIVATE_KNOWN_TEXT = (
    "Привіт, {name}! Я тебе знаю — ти підключений до HomeGroup CRM.\n\n"
    "Обирай розділ у меню нижче.\n\n"
    "Щоб отримувати сповіщення в групі лідерів — додай мене туди як учасника. "
    "Я одразу надішлю chat ID, який потрібно вставити в CRM (картка групи → Telegram Group ID)."
)

PRIVATE_UNKNOWN_TEXT = (
    "Привіт! На жаль, ваш акаунт (@{username}) не знайдено в HomeGroup CRM.\n"
    "Зверніться до адміністратора системи."
)

PRIVATE_NO_USERNAME_TEXT = (
    "Привіт! Не вдалося вас ідентифікувати — у вас не встановлений @username у Telegram.\n"
    "Встановіть його в налаштуваннях Telegram і спробуйте знову."
)


async def _find_admin_by_telegram(username: str) -> dict | None:
    username_clean = username.lstrip("@").lower()
    try:
        admins = await api_client.get_admins()
        for admin in admins:
            tg = (admin.get("telegram") or "").lstrip("@").lower()
            if tg and tg == username_clean:
                return admin
    except Exception:
        logger.exception("Failed to fetch admins for telegram lookup")
    return None


async def _handle_private(message: Message) -> None:
    username = message.from_user.username if message.from_user else None
    if not username:
        await message.answer(PRIVATE_NO_USERNAME_TEXT)
        return

    admin = await _find_admin_by_telegram(username)
    if admin is None:
        await message.answer(PRIVATE_UNKNOWN_TEXT.format(username=username))
        return

    name = admin.get("name") or "Адміне"
    await message.answer(
        PRIVATE_KNOWN_TEXT.format(name=name),
        reply_markup=private_main_keyboard(),
    )


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if message.chat.type == "private":
        await _handle_private(message)
    else:
        await message.answer(GROUP_START_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if message.chat.type == "private":
        await _handle_private(message)
    else:
        await message.answer(GROUP_START_TEXT)


@router.message(Command("test_notify"))
async def cmd_test_notify(message: Message, bot: Bot) -> None:
    await message.answer("Запускаю сповіщення про події за сьогодні...")
    await notify_upcoming_events(bot)
    await message.answer("Готово.")


@router.message(Command("test_conflict"))
async def cmd_test_conflict(message: Message, bot: Bot) -> None:
    await message.answer("Перевіряю накладки в розкладі (force)...")
    await check_conflicts(bot, force=True)
    await message.answer("Готово.")
