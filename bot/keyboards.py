from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def private_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Профіль"), KeyboardButton(text="Домашка")],
            [KeyboardButton(text="Відмітка присутніх"), KeyboardButton(text="Статистика")],
            [KeyboardButton(text="План"), KeyboardButton(text="Наступна домашка")],
        ],
        resize_keyboard=True,
    )


remove_keyboard = ReplyKeyboardRemove()
