import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import settings
from bot.handlers import common, attendance, plans, group_events, stats, private, profile, home_group, members, home_group_events
from bot.schedulers.notifications import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(common.router)
    dp.include_router(profile.router)
    dp.include_router(home_group.router)
    dp.include_router(members.router)
    dp.include_router(home_group_events.router)
    dp.include_router(private.router)
    dp.include_router(attendance.router)
    dp.include_router(plans.router)
    dp.include_router(group_events.router)
    dp.include_router(stats.router)

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    setup_scheduler(scheduler, bot)
    scheduler.start()

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
