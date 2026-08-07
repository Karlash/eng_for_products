from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.bot.middleware import AllowedUserMiddleware
from app.config import settings

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
dp.message.middleware(AllowedUserMiddleware())
dp.include_router(router)


async def start_polling() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
