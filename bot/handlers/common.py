import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.handlers.help_handler import main_kb as help_main_kb, main_text as help_main_text
from bot.keyboards import member_main_keyboard, private_main_keyboard
from bot.schedulers.notifications import check_conflicts, notify_upcoming_events
from bot.utils import find_admin_by_telegram, find_person_by_telegram

router = Router()
logger = logging.getLogger(__name__)

GROUP_START_TEXT = (
    "👋 <b>HomeGroup CRM Bot</b>\n\n"
    "<b>📋 Команди в чаті лідерів</b>\n"
    "• /plan — план наступної зустрічі\n"
    "• /attendance — відмітити присутніх\n"
    "• /stats — статистика відвідуваності за 1/3/6 місяців\n"
    "• /record_needs — записати потреби домашки після зустрічі\n"
    "• /anon_poll — запустити анонімний збір повідомлень до кінця дня\n\n"
    "<b>🔔 Автоматичні сповіщення</b>\n"
    "• За 7 днів до події і в день події — нагадування\n"
    "• Попередження про накладку зустрічі з іншою подією + сповіщення коли виправлено\n"
    "• Через годину після початку зустрічі — запит на відмітку присутніх\n"
    "• За 30 хв до зазначеного кінця домашки — запит на запис потреб\n\n"
    "<i>Кожен тип сповіщення можна вимкнути в кабінеті домашки.</i>"
)

PRIVATE_KNOWN_TEXT = (
    "Привіт, {name}! Я тебе знаю — ти підключений до HomeGroup CRM.\n\n"
    "{group_line}"
    "Обирай розділ у меню нижче.\n\n"
    "Щоб отримувати сповіщення в групі лідерів — додай мене туди як учасника. "
    "Я одразу надішлю chat ID, який потрібно вставити в CRM (картка групи → Telegram Group ID)."
)

MEMBER_KNOWN_TEXT = (
    "Привіт, {name}! Я тебе знаю — ти член домашки в HomeGroup CRM.\n\n"
    "{group_line}"
    "Обирай розділ у меню нижче."
)


def _group_line(group_name: str | None) -> str:
    return f"🏠 Твоя домашка: <b>{group_name}</b>\n\n" if group_name else ""

PRIVATE_UNKNOWN_TEXT = (
    "Привіт! На жаль, ваш акаунт (@{username}) не знайдено в HomeGroup CRM.\n"
    "Зверніться до адміністратора системи."
)

PRIVATE_NO_USERNAME_TEXT = (
    "Привіт! Не вдалося вас ідентифікувати — у вас не встановлений @username у Telegram.\n"
    "Встановіть його в налаштуваннях Telegram і спробуйте знову."
)


async def _handle_private(message: Message) -> None:
    username = message.from_user.username if message.from_user else None
    if not username:
        await message.answer(PRIVATE_NO_USERNAME_TEXT)
        return

    admin = await find_admin_by_telegram(username)
    if admin is not None:
        name = admin.get("name") or "Адміне"
        group_line = _group_line(admin.get("primaryGroupName"))
        await message.answer(
            PRIVATE_KNOWN_TEXT.format(name=name, group_line=group_line),
            parse_mode="HTML",
            reply_markup=private_main_keyboard(),
        )
        return

    person = await find_person_by_telegram(username)
    if person is not None:
        name = person.get("name") or "Друже"
        group_line = _group_line(person.get("primaryGroupName"))
        await message.answer(
            MEMBER_KNOWN_TEXT.format(name=name, group_line=group_line),
            parse_mode="HTML",
            reply_markup=member_main_keyboard(),
        )
        return

    await message.answer(PRIVATE_UNKNOWN_TEXT.format(username=username))


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if message.chat.type == "private":
        await _handle_private(message)
    else:
        await message.answer(GROUP_START_TEXT, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer(help_main_text(), parse_mode="HTML", reply_markup=help_main_kb())
    else:
        await message.answer(GROUP_START_TEXT, parse_mode="HTML")


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
