from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

_BACK = [[InlineKeyboardButton(text="← Назад", callback_data="help_main")]]

# ── Texts ─────────────────────────────────────────────────────────────────────

def main_text() -> str:
    return _main_text()


def main_kb() -> InlineKeyboardMarkup:
    return _main_kb()


def _main_text() -> str:
    text = (
        "<b>HomeGroup CRM Bot</b>\n\n"
        "Бот-помічник для лідерів домашніх груп. Дозволяє керувати групою, "
        "відмічати присутніх, переглядати статистику та отримувати сповіщення — "
        "все прямо в Telegram."
    )
    if settings.website_url:
        text += f"\n\n🌐 Сайт: {settings.website_url}"
    return text


_CONNECT_TEXT = (
    "<b>Як підключити бот у групу</b>\n\n"
    "1. Додайте бота до Telegram-групи вашої домашки\n"
    "2. Бот автоматично надішле ID групи — скопіюйте його\n"
    "3. У CRM відкрийте налаштування домашки та вставте ID у поле «Telegram-група»\n"
    "4. Готово — бот буде надсилати сповіщення у вашу групу\n\n"
    "<i>Щоб /record_needs і /anon_poll правильно ловили вашу відповідь, у "
    "@BotFather → Bot Settings → Group Privacy — вимкніть.</i>"
)

_PRIVATE_TEXT = (
    "<b>Можливості в приватному чаті (адмін)</b>\n\n"
    "<b>Основні кнопки:</b>\n"
    "• <b>Профіль</b> — перегляд і редагування власного профілю\n"
    "• <b>Домашка</b> — кабінет вашої домашки: статистика, наступна зустріч, "
    "учасники, події, запис потреб, анонімне опитування, налаштування\n"
    "• <b>Відмітка присутніх</b> — відмітити учасників після зустрічі\n"
    "• <b>План</b> — план зустрічі: перегляд, редагування, відправка в групу\n"
    "• <b>Сповіщення групи</b> — увімк/вимк автосповіщень (5 типів)\n"
    "• <b>Рандомна потреба</b> — випадкова активна потреба вашої домашки + "
    "швидка зміна статусу\n"
    "• <b>Додати потребу</b> — створити потребу для члена домашки або гостя\n\n"
    "<b>У кабінеті «Домашка» (inline):</b>\n"
    "• <b>Статистика</b> — за 1/3/6 місяців, дві сторінки (зустрічі + учасники)\n"
    "• <b>Наступна домашка</b> — переглянути дату, пропустити, перенести\n"
    "• <b>Учасники</b> — список з картками (перегляд + редагування полів)\n"
    "• <b>Події домашки</b> — створити/редагувати/видалити подію\n"
    "• <b>Записати потреби</b> — інтерактивний flow запису потреб після зустрічі\n"
    "• <b>Анонімне опитування</b> — запустити збір анонімних повідомлень "
    "(відповіді приходитимуть у ваш приват)\n"
    "• <b>Налаштування</b> — змінити назву, опис, день/час зустрічі, місце"
)

_LEADERS_TEXT = (
    "<b>Можливості в чаті лідерів</b>\n\n"
    "<b>📋 Команди</b>\n"
    "• /attendance — відмітити присутніх\n"
    "• /plan — переглянути план наступної домашки\n"
    "• /stats — статистика відвідуваності за 1/3/6 місяців\n"
    "• /record_needs — інтерактивний запис потреб домашки (з ✓ на тих, "
    "хто вже записаний). Звіт автоматично групується по людям + посилання "
    "на Telegram-акаунт\n"
    "• /anon_poll — запустити анонімний збір повідомлень. Члени домашки "
    "пишуть боту в приват — повідомлення анонімно приходять сюди до кінця дня\n\n"
    "<b>🔔 Автоматичні сповіщення</b>\n"
    "• За 7 днів до події — нагадування про подію групи\n"
    "• В день події — нагадування вранці\n"
    "• Накладка домашки з іншою подією — попередження про конфлікт розкладу\n"
    "• Виправлення накладки — сповіщення коли конфлікт усунено\n"
    "• Через годину після початку зустрічі — запит на відмітку присутніх\n"
    "• За 30 хв до зазначеного кінця зустрічі — запит на запис потреб\n\n"
    "<i>Сповіщення працюють лише якщо у налаштуваннях групи вказано Telegram-групу. "
    "Кожен тип сповіщення можна вимкнути в кабінеті домашки.</i>"
)

_MEMBER_TEXT = (
    "<b>Можливості в приватному чаті (член домашки)</b>\n\n"
    "• <b>Рандомна потреба</b> — випадкова активна потреба вашої домашки "
    "для молитви\n"
    "• <b>Подякувати за молитву</b> — ваші активні потреби; можна позначити "
    "«Отримано відповідь» чи «Не актуальна»\n"
    "• <b>Додати потребу</b> — створити власну потребу (текст), система "
    "збереже від вашого імені\n\n"
    "<b>🤫 Анонімне опитування</b>\n"
    "Якщо адмін запустив анонімний збір — будь-яке ваше повідомлення в цьому "
    "чаті буде анонімно передано лідерам до кінця дня."
)

_CONTACT_TEXT = (
    "<b>Питання та пропозиції</b>\n\n"
    "З питаннями по роботі боту або пропозиціями щодо нових функцій звертайтесь до:\n\n"
    "@Stepll\n\n"
    "<i>Намагаємось відповідати якомога швидше 🙂</i>"
)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Як підключити бот у групу", callback_data="help_connect")],
        [InlineKeyboardButton(text="💬 Адмін — приватний чат", callback_data="help_private")],
        [InlineKeyboardButton(text="🙋 Член домашки — приватний чат", callback_data="help_member")],
        [InlineKeyboardButton(text="👥 Чат лідерів", callback_data="help_leaders")],
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


@router.callback_query(F.data == "help_member")
async def cb_help_member(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _MEMBER_TEXT, parse_mode="HTML",
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
