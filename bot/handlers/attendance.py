from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("attendance"))
async def cmd_attendance(message: Message) -> None:
    # TODO: FSM flow — select members present/absent, submit to API
    await message.answer("Функція відмітки присутніх — в розробці.")
