from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import notif_settings as ns
from bot.handlers.private import _get_admin_group

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

_LABELS: dict[str, tuple[str, str]] = {
    "event_7days":          ("📅 7 днів",      "📅 За 7 днів до події\nНагадування у Telegram-групу за тиждень до події."),
    "event_day":            ("📅 День події",  "📅 В день події\nНагадування вранці у день події."),
    "conflict":             ("⚡ Накладка",    "⚡ Накладка домашки з іншою подією\nСповіщення, якщо час домашки збігається з іншою подією."),
    "conflict_resolved":    ("✔ Виправлення", "✔ Виправлення накладки\nСповіщення, коли конфлікт розкладу усунено."),
    "attendance_ask":       ("🙋 Відмітка",   "🙋 Нагадування відмітити присутніх\nЗапит через годину після початку домашки."),
    "needs_recording_ask":  ("📝 Запис потреб", "📝 Запис потреб домашки\nЗапит за 30 хв до зазначеного кінця домашки."),
}


def _notif_text(settings: dict[str, bool]) -> str:
    lines = ["<b>Сповіщення групи</b>\n"]
    for key, (_, desc) in _LABELS.items():
        emoji = "✅" if settings[key] else "❌"
        title, rest = desc.split("\n", 1)
        lines.append(f"{title} {emoji}\n{rest}\n")
    return "\n".join(lines)


def _notif_kb(group_id: int, settings: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{'✅' if settings[key] else '❌'} {short}",
            callback_data=f"notif_toggle_{group_id}_{key}",
        )]
        for key, (short, _) in _LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "Сповіщення групи")
async def btn_notif(message: Message) -> None:
    result = await _get_admin_group(message)
    if result is None:
        return
    _, group_id = result
    settings = await ns.get(group_id)
    await message.answer(
        _notif_text(settings),
        parse_mode="HTML",
        reply_markup=_notif_kb(group_id, settings),
    )


@router.callback_query(F.data.startswith("notif_toggle_"))
async def cb_notif_toggle(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    # notif_toggle_{group_id}_{key} — key may contain underscores
    group_id = int(parts[2])
    key = "_".join(parts[3:])
    if key not in ns.KEYS:
        await callback.answer("Невідоме налаштування.", show_alert=True)
        return
    settings = await ns.toggle(group_id, key)
    await callback.message.edit_text(
        _notif_text(settings),
        parse_mode="HTML",
        reply_markup=_notif_kb(group_id, settings),
    )
    await callback.answer()
