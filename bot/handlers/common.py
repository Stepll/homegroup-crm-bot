from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

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
