from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.api_client import api_client

router = Router()

SEPARATOR = "------------------"


def _format_date(date: str) -> str:
    """'2026-05-15' → '15.05.2026'"""
    try:
        y, m, d = date.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return date


def build_telegram_map(people: list, admins: list) -> dict[str, str]:
    """name (or full name) → telegram handle (without @)"""
    result: dict[str, str] = {}
    for person in people + admins:
        telegram = (person.get("telegram") or "").lstrip("@").strip()
        if not telegram:
            continue
        name = (person.get("name") or "").strip()
        last = (person.get("lastName") or "").strip()
        if name:
            result[name.lower()] = telegram
        if name and last:
            result[f"{name} {last}".lower()] = telegram
    return result


def resolve_responsible(responsible: str | None, tg_map: dict[str, str]) -> str:
    if not responsible:
        return ""
    responsible = responsible.strip()
    if responsible.startswith("@"):
        return responsible
    key = responsible.lower()
    if key in tg_map:
        return f"@{tg_map[key]}"
    return responsible


def format_plan(plan: dict, date: str, tg_map: dict[str, str]) -> str:
    blocks = plan.get("blocks", [])
    timeline = [b for b in blocks if (b.get("time") or "").strip()]
    footer = [b for b in blocks if not (b.get("time") or "").strip()]

    lines = [f"План на {_format_date(date)}", SEPARATOR]

    for block in timeline:
        responsible = resolve_responsible(block.get("responsible"), tg_map)
        line = f"{block['time']} - {block['title']}"
        if responsible:
            line += f": {responsible}"
        lines.append(line)
        for info_line in (block.get("info") or "").splitlines():
            if info_line.strip():
                lines.append(f"   • {info_line.strip()}")

    if footer:
        lines.append(SEPARATOR)
        for block in footer:
            responsible = resolve_responsible(block.get("responsible"), tg_map)
            title = block.get("title", "")
            if responsible:
                lines.append(f"{responsible} - {title}")
            else:
                lines.append(title)

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

    people, admins = await api_client.get_people(), await api_client.get_admins()
    tg_map = build_telegram_map(people, admins)

    await message.answer(format_plan(plan, next_date, tg_map))
