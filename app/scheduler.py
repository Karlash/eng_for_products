import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.bot import bot
from app.bot.practice import send_practice_word
from app.config import settings
from app.db import async_session

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.timezone)


async def scheduled_send_job() -> None:
    if not settings.telegram_allowed_user_id:
        return
    async with async_session() as session:
        sent = await send_practice_word(bot, settings.telegram_allowed_user_id, session)
    if not sent:
        logger.info("Scheduled send skipped: nothing due and no new-word quota left.")


def build_scheduler() -> AsyncIOScheduler:
    for time_str in settings.schedule_times_list:
        hour, minute = (int(part) for part in time_str.split(":"))
        scheduler.add_job(
            scheduled_send_job,
            CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
            id=f"send_{time_str}",
            replace_existing=True,
        )
    return scheduler
