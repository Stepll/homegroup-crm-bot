from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.schedulers.notifications import check_conflicts, notify_upcoming_events

router = Router()


START_TEXT = (
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


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(START_TEXT)


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
