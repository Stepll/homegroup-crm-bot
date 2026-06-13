import logging

from bot.api_client import api_client

logger = logging.getLogger(__name__)


async def find_admin_by_telegram(username: str) -> dict | None:
    username_clean = username.lstrip("@").lower()
    try:
        admins = await api_client.get_admins()
        for admin in admins:
            tg = (admin.get("telegram") or "").lstrip("@").lower()
            if tg and tg == username_clean:
                return admin
    except Exception:
        logger.exception("Failed to fetch admins")
    return None


async def find_person_by_telegram(username: str) -> dict | None:
    username_clean = username.lstrip("@").lower()
    try:
        people = await api_client.get_people()
        for person in people:
            if person.get("isAdmin"):
                continue
            tg = (person.get("telegram") or "").lstrip("@").lower()
            if tg and tg == username_clean:
                return person
    except Exception:
        logger.exception("Failed to fetch people")
    return None
