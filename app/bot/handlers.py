from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from app.bot.practice import get_bot_state, send_practice_word
from app.db import async_session
from app.models import LearningProgress, Word
from app.services.progress import expected_answer, judge_exact, record_answer

router = Router()

HELP_TEXT = (
    "Команды:\n"
    "/next — прислать слово для практики\n"
    "/add english - russian — добавить слово вручную\n"
    "/stats — статистика\n"
    "/help — эта справка\n\n"
    "Просто ответьте текстом на присланное слово, чтобы проверить перевод."
)


@router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    async with async_session() as session:
        sent = await send_practice_word(message.bot, message.chat.id, session)
    if not sent:
        await message.answer(
            "Сейчас нечего повторять, а дневной лимит новых слов исчерпан (или словарь пуст). Загляните позже."
        )


@router.message(Command("add"))
async def cmd_add(message: Message) -> None:
    raw = (message.text or "").removeprefix("/add").strip()
    if " - " not in raw:
        await message.answer("Формат: /add english - russian")
        return
    english, russian = raw.split(" - ", 1)
    english, russian = english.strip(), russian.strip()
    if not english or not russian:
        await message.answer("Формат: /add english - russian")
        return

    async with async_session() as session:
        word = Word(english=english, russian=russian, source="manual")
        session.add(word)
        await session.flush()
        session.add(LearningProgress(word_id=word.id, status="new"))
        await session.commit()

    await message.answer(f"Добавлено: {english} — {russian}")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    async with async_session() as session:
        total_words = (await session.execute(select(func.count(Word.id)))).scalar_one()
        status_rows = (
            await session.execute(select(LearningProgress.status, func.count()).group_by(LearningProgress.status))
        ).all()
        status_counts = {"new": 0, "learning": 0, "learned": 0}
        status_counts.update({s: c for s, c in status_rows})
        total_correct = (await session.execute(select(func.sum(LearningProgress.total_correct)))).scalar() or 0
        total_wrong = (await session.execute(select(func.sum(LearningProgress.total_wrong)))).scalar() or 0

    await message.answer(
        f"Всего слов: {total_words}\n"
        f"Новых: {status_counts['new']} · Учатся: {status_counts['learning']} · Выучено: {status_counts['learned']}\n"
        f"Правильно: {total_correct} · Неправильно: {total_wrong}"
    )


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    await message.answer("Импорт слов с фото появится позже — пока добавляйте слова через /add.")


@router.message(F.text)
async def handle_answer(message: Message) -> None:
    async with async_session() as session:
        state = await get_bot_state(session)
        if state.pending_word_id is None:
            await message.answer("Сейчас не жду ответа. Используйте /next, чтобы получить слово.")
            return

        word = await session.get(Word, state.pending_word_id)
        direction = state.pending_direction
        if word is None or direction is None:
            state.pending_word_id = None
            state.pending_direction = None
            state.pending_asked_at = None
            await session.commit()
            await message.answer("Что-то пошло не так, попробуйте /next ещё раз.")
            return

        user_answer = message.text or ""
        was_correct = judge_exact(word, direction, user_answer)
        await record_answer(session, word, direction, user_answer, was_correct, judged_by="normalized_match")

        state.pending_word_id = None
        state.pending_direction = None
        state.pending_asked_at = None
        await session.commit()

    if was_correct:
        await message.answer("✅ Верно!")
    else:
        await message.answer(f"❌ Неверно. Правильный ответ: {expected_answer(word, direction)}")
