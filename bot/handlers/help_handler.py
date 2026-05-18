from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

_BACK = [[InlineKeyboardButton(text="← Назад", callback_data="help_main")]]

# ── Texts ─────────────────────────────────────────────────────────────────────

def _main_text() -> str:
    site_line = f"\n🌐 Сайт: {settings.website_url}" if settings.website_url else ""
    return (
        "<b>HomeGroup CRM Bot</b>\n\n"
        "Бот-помічник для лідерів домашніх груп. Дозволяє керувати групою, "
        "відмічати присутніх, переглядати статистику та отримувати сповіщення — "
        "все прямо в Telegram."
        f"{site_line}"
    )


_CONNECT_TEXT = (
    "<b>Як підключити бот у групу</b>\n\n"
    "1. Додайте бота до Telegram-групи вашої домашки\n"
    "2. Призначте бота <b>адміністратором</b> групи (потрібно для надсилання повідомлень)\n"
    "3. Відправте в групі команду <code>/id</code> — бот відповість ID групи\n"
    "4. У CRM відкрийте налаштування домашки та вставте цей ID у поле «Telegram-група»\n"
    "5. Готово — бот буде надсилати сповіщення у вашу групу"
)

_PRIVATE_TEXT = (
    "<b>Можливості в приватному чаті</b>\n\n"
    "• <b>Профіль</b> — перегляд і редагування вашого профілю\n"
    "• <b>Домашка</b> — налаштування домашньої групи\n"
    "• <b>Відмітка присутніх</b> — відмітити учасників після зустрічі\n"
    "• <b>Статистика</b> — статистика відвідуваності по зустрічах\n"
    "• <b>План</b> — план зустрічі: перегляд, редагування, відправка в групу\n"
    "• <b>Наступна домашка</b> — дата та налаштування наступної зустрічі\n"
    "• <b>Учасники</b> — список членів групи\n"
    "• <b>Події домашки</b> — особливі події групи\n"
    "• <b>Сповіщення групи</b> — налаштування автоматичних сповіщень"
)

_LEADERS_TEXT = (
    "<b>Можливості в чаті лідерів</b>\n\n"
    "<b>Команди:</b>\n"
    "• /plan — переглянути план наступної зустрічі\n\n"
    "<b>Автоматичні сповіщення:</b>\n"
    "• За 7 днів до події церкви — нагадування про подію\n"
    "• В день події церкви — нагадування вранці\n"
    "• Накладка зустрічі з іншою подією — попередження про конфлікт розкладу\n"
    "• Виправлення накладки — сповіщення коли конфлікт вирішено\n"
    "• Нагадування відмітити присутніх — через годину після початку зустрічі\n\n"
    "<i>Сповіщення надсилаються лише якщо у налаштуваннях вказано Telegram-групу.</i>"
)

_CONTACT_TEXT = (
    "<b>Питання та пропозиції</b>\n\n"
    "З питаннями по роботі боту або пропозиціями щодо нових функцій звертайтесь до:\n\n"
    "@stepankobrii\n\n"
    "<i>Намагаємось відповідати якомога швидше 🙂</i>"
)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Як підключити бот у групу", callback_data="help_connect")],
        [InlineKeyboardButton(text="💬 Можливості в приватному чаті", callback_data="help_private")],
        [InlineKeyboardButton(text="👥 Можливості в чаті лідерів", callback_data="help_leaders")],
        [InlineKeyboardButton(text="✉️ Питання та пропозиції", callback_data="help_contact")],
    ])


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.message(F.text == "Допомога")
async def btn_help(message: Message) -> None:
    await message.answer(_main_text(), parse_mode="HTML", reply_markup=_main_kb())


@router.callback_query(F.data == "help_main")
async def cb_help_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text(_main_text(), parse_mode="HTML", reply_markup=_main_kb())
    await callback.answer()


@router.callback_query(F.data == "help_connect")
async def cb_help_connect(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _CONNECT_TEXT, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=_BACK),
    )
    await callback.answer()


@router.callback_query(F.data == "help_private")
async def cb_help_private(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _PRIVATE_TEXT, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=_BACK),
    )
    await callback.answer()


@router.callback_query(F.data == "help_leaders")
async def cb_help_leaders(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _LEADERS_TEXT, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=_BACK),
    )
    await callback.answer()


@router.callback_query(F.data == "help_contact")
async def cb_help_contact(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _CONTACT_TEXT, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=_BACK),
    )
    await callback.answer()
