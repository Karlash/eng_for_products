from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BotState, utcnow
from app.services.progress import mark_word_asked, select_word_to_send


async def get_bot_state(session: AsyncSession) -> BotState:
    state = await session.get(BotState, 1)
    if state is None:
        state = BotState(id=1)
        session.add(state)
        await session.flush()
    return state


async def send_practice_word(bot: Bot, chat_id: int, session: AsyncSession) -> bool:
    picked = await select_word_to_send(session)
    if picked is None:
        return False
    word, direction = picked

    await mark_word_asked(session, word.id)

    state = await get_bot_state(session)
    state.pending_word_id = word.id
    state.pending_direction = direction
    state.pending_asked_at = utcnow()
    await session.commit()

    if direction == "en_to_ru":
        text = f"🇬🇧 {word.english}\n\nПереведи на русский:"
    else:
        text = f"🇷🇺 {word.russian}\n\nTranslate to English:"
    await bot.send_message(chat_id, text)
    return True
