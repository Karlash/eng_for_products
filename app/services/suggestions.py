import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session
from app.models import LearningProgress, Word
from app.services.claude_client import SuggestedWord, suggest_new_words
from app.services.dedup import filter_new_pairs

logger = logging.getLogger(__name__)


async def generate_candidates(session: AsyncSession, batch_size: int | None = None) -> list[SuggestedWord]:
    """Ask Claude for new words themed around the dictionary's existing topics, deduped against it."""
    if not settings.anthropic_api_key:
        return []

    topics = [
        t
        for (t,) in (await session.execute(select(Word.topic).distinct().where(Word.topic.is_not(None)))).all()
        if t
    ]
    sample_pairs = (
        await session.execute(select(Word.english, Word.russian).order_by(func.random()).limit(15))
    ).all()

    candidates = await suggest_new_words(topics, sample_pairs, batch_size or settings.suggestion_batch_size)
    by_key = {c.english.strip().lower(): c for c in candidates}
    new_pairs = await filter_new_pairs(session, [(c.english, c.russian) for c in candidates])
    return [by_key[en.strip().lower()] for en, _ru in new_pairs if en.strip().lower() in by_key]


async def insert_words(session: AsyncSession, candidates: list[SuggestedWord]) -> int:
    added = 0
    for candidate in candidates:
        word = Word(
            english=candidate.english,
            russian=candidate.russian,
            part_of_speech=candidate.part_of_speech,
            topic=candidate.topic,
            source="suggested",
        )
        session.add(word)
        await session.flush()
        session.add(LearningProgress(word_id=word.id, status="new"))
        added += 1
    await session.commit()
    return added


async def run_suggestion_top_up(force: bool = False) -> int:
    """Fetch and auto-insert a batch of suggested words if the new-word pool is low. Returns count added."""
    if not settings.anthropic_api_key:
        return 0

    async with async_session() as session:
        new_count = (
            await session.execute(select(func.count(LearningProgress.id)).where(LearningProgress.status == "new"))
        ).scalar_one()
        if not force and new_count >= settings.suggestion_threshold:
            logger.info("Suggestion top-up skipped: %s new words already queued.", new_count)
            return 0

        candidates = await generate_candidates(session)
        added = await insert_words(session, candidates)
        logger.info("Suggestion top-up added %s new words.", added)
        return added
