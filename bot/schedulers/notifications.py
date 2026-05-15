import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

logger = logging.getLogger(__name__)


async def notify_upcoming_events(bot: Bot) -> None:
    # TODO: fetch groups with TelegramGroupId, check upcoming events via /cabinet,
    #       send notifications to TelegramGroupId chats
    logger.info("notify_upcoming_events triggered")


async def notify_meeting_plan(bot: Bot) -> None:
    # TODO: fetch groups, get plan for next meeting date, send formatted plan to group chats
    logger.info("notify_meeting_plan triggered")


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    # Notify about upcoming events — every day at 09:00 Kyiv time
    scheduler.add_job(
        notify_upcoming_events,
        trigger="cron",
        hour=9,
        minute=0,
        kwargs={"bot": bot},
        id="notify_upcoming_events",
    )
    # Send meeting plan — day before meeting at 18:00 Kyiv time
    scheduler.add_job(
        notify_meeting_plan,
        trigger="cron",
        hour=18,
        minute=0,
        kwargs={"bot": bot},
        id="notify_meeting_plan",
    )
