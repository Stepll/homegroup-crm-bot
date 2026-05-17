from aiogram import F, Router
from aiogram.types import Message

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(F.text == "Домашка")
async def btn_home_group(message: Message) -> None:
    await message.answer("Розділ «Домашка» — незабаром.")


@router.message(F.text == "Відмітка присутніх")
async def btn_attendance(message: Message) -> None:
    await message.answer("Розділ «Відмітка присутніх» — незабаром.")


@router.message(F.text == "Статистика")
async def btn_stats(message: Message) -> None:
    await message.answer("Розділ «Статистика» — незабаром.")


@router.message(F.text == "План")
async def btn_plan(message: Message) -> None:
    await message.answer("Розділ «План» — незабаром.")


@router.message(F.text == "Наступна домашка")
async def btn_next_meeting(message: Message) -> None:
    await message.answer("Розділ «Наступна домашка» — незабаром.")
