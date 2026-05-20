from bot.api_client import api_client

KEYS = ["event_7days", "event_day", "conflict", "conflict_resolved", "attendance_ask"]
DEFAULTS: dict[str, bool] = {k: True for k in KEYS}


async def get(group_id: int) -> dict[str, bool]:
    try:
        return await api_client.get_notif_settings(group_id)
    except Exception:
        return dict(DEFAULTS)


async def toggle(group_id: int, key: str) -> dict[str, bool]:
    settings = await get(group_id)
    if key in settings:
        settings[key] = not settings[key]
    return await api_client.update_notif_settings(group_id, settings)
