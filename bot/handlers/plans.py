from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("plan"))
async def cmd_plan(message: Message) -> None:
    # TODO: fetch plan for this group from API and format it
    await message.answer("Функція плану — в розробці.")
