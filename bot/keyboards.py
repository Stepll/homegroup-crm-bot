from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def private_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Рандомна потреба")],
            [KeyboardButton(text="Профіль"), KeyboardButton(text="Домашка")],
            [KeyboardButton(text="Відмітка присутніх"), KeyboardButton(text="План")],
            [KeyboardButton(text="Сповіщення групи"), KeyboardButton(text="Допомога")],
        ],
        resize_keyboard=True,
    )


remove_keyboard = ReplyKeyboardRemove()
