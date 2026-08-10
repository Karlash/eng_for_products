import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from app.bot.practice import continue_session, get_bot_state, send_practice_word
from app.config import settings
from app.db import async_session
from app.models import LearningProgress, Word
from app.services.claude_client import judge_translation, ocr_extract_words
from app.services.dedup import filter_new_pairs
from app.services.progress import expected_answer, judge_exact, record_answer
from app.services.suggestions import run_suggestion_top_up

router = Router()

HELP_TEXT = (
    "Команды:\n"
    "/next — прислать слово для практики\n"
    "/add english - russian — добавить слово вручную\n"
    "/suggest — подобрать новые слова по темам вашего словаря (PM/IT)\n"
    "/stats — статистика\n"
    "/help — эта справка\n\n"
    "Просто ответьте текстом на присланное слово, чтобы проверить перевод.\n\n"
    "Пришлите фото страницы бумажного словаря, чтобы загрузить слова пачкой — "
    "бот распознает пары слово–перевод и предложит подтвердить импорт "
    "(/confirm_import или /cancel)."
)

MAX_PREVIEW_ITEMS = 25


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


@router.message(Command("suggest"))
async def cmd_suggest(message: Message) -> None:
    if not settings.anthropic_api_key:
        await message.answer("Подбор слов недоступен — не настроен Anthropic API-ключ.")
        return
    await message.answer("Подбираю новые слова по вашим темам...")
    added = await run_suggestion_top_up(force=True)
    if added:
        await message.answer(f"Добавлено {added} новых слов. Посмотреть — /stats или в веб-словаре.")
    else:
        await message.answer("Не удалось подобрать новые уникальные слова — попробуйте позже.")


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
    if not settings.anthropic_api_key:
        await message.answer("Импорт фото недоступен — не настроен Anthropic API-ключ.")
        return

    await message.answer("Распознаю слова на фото...")

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buffer = await message.bot.download_file(file.file_path)
    image_bytes = buffer.read()

    try:
        extracted = await ocr_extract_words(image_bytes)
    except Exception:
        await message.answer("Не удалось распознать слова на фото. Попробуйте другое фото или /add вручную.")
        return

    if not extracted:
        await message.answer("На фото не нашлось пар слово–перевод.")
        return

    candidates = [(w.english, w.russian) for w in extracted]
    pos_by_english = {w.english.strip().lower(): w.part_of_speech for w in extracted}

    async with async_session() as session:
        new_pairs = await filter_new_pairs(session, candidates)
        state = await get_bot_state(session)
        if not new_pairs:
            state.pending_import_json = None
            await session.commit()
            await message.answer("Все найденные слова уже есть в словаре — добавлять нечего.")
            return

        payload = [
            {"english": en, "russian": ru, "part_of_speech": pos_by_english.get(en.strip().lower())}
            for en, ru in new_pairs
        ]
        state.pending_import_json = json.dumps(payload, ensure_ascii=False)
        await session.commit()

    preview_lines = [f"{en} — {ru}" for en, ru in new_pairs[:MAX_PREVIEW_ITEMS]]
    preview = "\n".join(preview_lines)
    more = f"\n…и ещё {len(new_pairs) - MAX_PREVIEW_ITEMS}" if len(new_pairs) > MAX_PREVIEW_ITEMS else ""
    await message.answer(
        f"Найдено {len(new_pairs)} новых слов:\n\n{preview}{more}\n\n"
        "Добавить их в словарь? /confirm_import — да, /cancel — отмена."
    )


@router.message(Command("confirm_import"))
async def cmd_confirm_import(message: Message) -> None:
    async with async_session() as session:
        state = await get_bot_state(session)
        if not state.pending_import_json:
            await message.answer("Нечего подтверждать — сначала пришлите фото словаря.")
            return

        payload = json.loads(state.pending_import_json)
        added = 0
        for item in payload:
            word = Word(
                english=item["english"],
                russian=item["russian"],
                part_of_speech=item.get("part_of_speech"),
                source="imported_ocr",
            )
            session.add(word)
            await session.flush()
            session.add(LearningProgress(word_id=word.id, status="new"))
            added += 1

        state.pending_import_json = None
        await session.commit()

    await message.answer(f"Добавлено {added} слов.")


@router.message(Command("cancel"))
async def cmd_cancel_import(message: Message) -> None:
    async with async_session() as session:
        state = await get_bot_state(session)
        if not state.pending_import_json:
            await message.answer("Нечего отменять.")
            return
        state.pending_import_json = None
        await session.commit()
    await message.answer("Импорт отменён.")


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
        claude_explanation = None
        if judge_exact(word, direction, user_answer):
            was_correct = True
            judged_by = "normalized_match"
        elif settings.anthropic_api_key:
            result = await judge_translation(word.english, word.russian, direction, user_answer)
            was_correct = result.correct
            judged_by = "claude"
            claude_explanation = result.explanation
        else:
            was_correct = False
            judged_by = "normalized_match"

        await record_answer(
            session, word, direction, user_answer, was_correct, judged_by=judged_by, claude_explanation=claude_explanation
        )

        state.pending_word_id = None
        state.pending_direction = None
        state.pending_asked_at = None
        await session.commit()

    if was_correct:
        text = "✅ Верно!"
        if claude_explanation:
            text += f" {claude_explanation}"
    else:
        text = f"❌ Неверно. Правильный ответ: {expected_answer(word, direction)}"
        if claude_explanation:
            text += f"\n{claude_explanation}"
    await message.answer(text)

    async with async_session() as session:
        await continue_session(message.bot, message.chat.id, session)
