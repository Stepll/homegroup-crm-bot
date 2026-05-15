from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.schedulers.notifications import notify_upcoming_events

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Вітаю! Я бот HomeGroup CRM.\n\n"
        "Доступні команди:\n"
        "/plan — план наступної зустрічі\n"
        "/attendance — відмітити присутніх\n"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команди:\n"
        "/plan — переглянути план зустрічі групи\n"
        "/attendance — відмітити присутніх на зустрічі\n"
    )


@router.message(Command("test_notify"))
async def cmd_test_notify(message: Message, bot: Bot) -> None:
    await message.answer("Запускаю сповіщення про події за сьогодні...")
    await notify_upcoming_events(bot)
    await message.answer("Готово.")
