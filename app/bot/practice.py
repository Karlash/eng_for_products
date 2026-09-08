from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Не знаю", callback_data="dont_know")]]
    )
    await bot.send_message(chat_id, text, reply_markup=keyboard)
    return True


async def start_session(bot: Bot, chat_id: int, session: AsyncSession, word_count: int) -> bool:
    """Send the first word of a multi-word session; the rest follow one at a time as each is answered."""
    sent = await send_practice_word(bot, chat_id, session)
    if sent:
        state = await get_bot_state(session)
        state.session_remaining = max(word_count - 1, 0)
        await session.commit()
    return sent


async def continue_session(bot: Bot, chat_id: int, session: AsyncSession) -> None:
    """Send the next word in an in-progress session, if any words remain."""
    state = await get_bot_state(session)
    if state.session_remaining <= 0:
        return
    state.session_remaining -= 1
    await session.commit()

    sent = await send_practice_word(bot, chat_id, session)
    if not sent:
        state.session_remaining = 0
        await session.commit()
