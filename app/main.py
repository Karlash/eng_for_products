import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.bot.bot import bot, start_polling
from app.config import settings
from app.db import init_db
from app.scheduler import build_scheduler
from app.web.routes import router as web_router

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    bot_task = None
    scheduler = None
    if settings.telegram_bot_token:
        bot_task = asyncio.create_task(start_polling())
        scheduler = build_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    if bot_task is not None:
        bot_task.cancel()
        await bot.session.close()


app = FastAPI(title="Vocab App", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(web_router)
