from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.api_client import api_client

router = Router()


def _format_date(date: str) -> str:
    """'2026-05-15' → '15.05.2026'"""
    try:
        y, m, d = date.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return date


def format_plan(plan: dict, date: str) -> str:
    lines = [f"📋 <b>План зустрічі — {_format_date(date)}</b>"]
    if plan.get("appliedTemplateName"):
        lines.append(f"<i>{plan['appliedTemplateName']}</i>")
    lines.append("")
    for block in plan.get("blocks", []):
        line = f"🕐 {block['time']} — <b>{block['title']}</b>"
        if block.get("responsible"):
            line += f" ({block['responsible']})"
        lines.append(line)
        if block.get("info"):
            lines.append(f"   <i>{block['info']}</i>")
    return "\n".join(lines)


@router.message(Command("plan"))
async def cmd_plan(message: Message) -> None:
    chat_id = str(message.chat.id)

    groups = await api_client.get_groups()
    group = next((g for g in groups if g.get("telegramGroupId") == chat_id), None)

    if not group:
        await message.answer("Ця група не підключена до CRM або TelegramGroupId не вказано.")
        return

    cabinet = await api_client.get_cabinet(group["id"])
    next_date = cabinet.get("nextMeetingDate")

    if not next_date:
        await message.answer("Немає запланованих зустрічей.")
        return

    plan = await api_client.get_plan(group["id"], next_date)

    if not plan:
        await message.answer(f"Плану на {_format_date(next_date)} ще немає.")
        return

    await message.answer(format_plan(plan, next_date), parse_mode="HTML")
