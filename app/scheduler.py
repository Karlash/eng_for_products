import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.bot import bot
from app.bot.practice import start_session
from app.config import settings
from app.db import async_session
from app.services.suggestions import run_suggestion_top_up

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.timezone)


async def scheduled_send_job() -> None:
    if not settings.telegram_allowed_user_id:
        return
    async with async_session() as session:
        sent = await start_session(bot, settings.telegram_allowed_user_id, session, settings.words_per_session)
    if not sent:
        logger.info("Scheduled send skipped: nothing due and no new-word quota left.")


async def suggestion_top_up_job() -> None:
    await run_suggestion_top_up(force=False)


def build_scheduler() -> AsyncIOScheduler:
    for time_str in settings.schedule_times_list:
        hour, minute = (int(part) for part in time_str.split(":"))
        scheduler.add_job(
            scheduled_send_job,
            CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
            id=f"send_{time_str}",
            replace_existing=True,
        )

    sugg_hour, sugg_minute = (int(part) for part in settings.suggestion_schedule_time.split(":"))
    scheduler.add_job(
        suggestion_top_up_job,
        CronTrigger(
            day_of_week=settings.suggestion_schedule_day,
            hour=sugg_hour,
            minute=sugg_minute,
            timezone=settings.timezone,
        ),
        id="suggestion_top_up",
        replace_existing=True,
    )
    return scheduler
