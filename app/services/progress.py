"""Word selection and the spaced-repetition state machine.

Rule: 4 correct answers within a rolling 30-day window marks a word as
`learned`; it then resurfaces exactly once, 30 days later, as a reinforcement
check. Answered correctly, it stays learned. Answered incorrectly, it's
demoted back to `learning` and the cycle restarts.
"""

import random
import re
import string
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AnswerLog, LearningProgress, Word, utcnow

CYCLE_WINDOW = timedelta(days=30)
REINFORCEMENT_DELAY = timedelta(days=30)
RETRY_SOON_DELAY = timedelta(hours=4)
REQUIRED_CORRECT_IN_CYCLE = 4
# Floor of 2 days between repeat exposures (instead of 1) so a word has time
# to fade a bit before it's asked again, rather than feeling drilled.
CYCLE_INTERVALS = {1: timedelta(days=2), 2: timedelta(days=4), 3: timedelta(days=7)}


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text)
    return text


def expected_answer(word: Word, direction: str) -> str:
    return word.russian if direction == "en_to_ru" else word.english


def judge_exact(word: Word, direction: str, user_answer: str) -> bool:
    return normalize(user_answer) == normalize(expected_answer(word, direction))


def pick_direction() -> str:
    return random.choice(["en_to_ru", "ru_to_en"])


async def new_words_sent_today(session: AsyncSession) -> int:
    start_of_today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count(LearningProgress.id)).where(
            LearningProgress.last_asked_at >= start_of_today,
            (LearningProgress.total_correct + LearningProgress.total_wrong) <= 1,
        )
    )
    return result.scalar_one()


async def select_word_to_send(session: AsyncSession) -> tuple[Word, str] | None:
    now = utcnow()

    # Random among everything currently due, not just the single oldest — a small
    # dictionary with several words due around the same time otherwise cycles
    # through them in the same predictable order every session.
    due_candidates = (
        (
            await session.execute(
                select(Word)
                .join(LearningProgress)
                .where(LearningProgress.next_review_at.is_not(None), LearningProgress.next_review_at <= now)
            )
        )
        .scalars()
        .all()
    )
    if due_candidates:
        return random.choice(due_candidates), pick_direction()

    if await new_words_sent_today(session) < settings.max_new_words_per_day:
        new_word = (
            await session.execute(
                select(Word)
                .join(LearningProgress)
                .where(LearningProgress.status == "new")
                .order_by(func.random())
                .limit(1)
            )
        ).scalar_one_or_none()
        if new_word is not None:
            return new_word, pick_direction()

    return None


async def mark_word_asked(session: AsyncSession, word_id: int) -> None:
    progress = await session.scalar(select(LearningProgress).where(LearningProgress.word_id == word_id))
    if progress is not None:
        progress.last_asked_at = utcnow()
        await session.commit()


async def record_answer(
    session: AsyncSession,
    word: Word,
    direction: str,
    user_answer: str | None,
    was_correct: bool,
    judged_by: str,
    claude_explanation: str | None = None,
) -> None:
    now = utcnow()
    session.add(
        AnswerLog(
            word_id=word.id,
            asked_at=now,
            direction=direction,
            user_answer=user_answer,
            was_correct=was_correct,
            judged_by=judged_by,
            claude_explanation=claude_explanation,
        )
    )

    progress = await session.scalar(select(LearningProgress).where(LearningProgress.word_id == word.id))
    if progress is None:
        await session.commit()
        return

    progress.last_asked_at = now

    if progress.status == "learned":
        # This was the one-time reinforcement check, 30 days after learning.
        if was_correct:
            progress.total_correct += 1
            progress.next_review_at = None
        else:
            progress.total_wrong += 1
            progress.status = "learning"
            progress.correct_count_in_cycle = 0
            progress.cycle_start_at = None
            progress.learned_at = None
            progress.next_review_at = now
        await session.commit()
        return

    if was_correct:
        progress.total_correct += 1
        if progress.cycle_start_at is not None and (now - progress.cycle_start_at) > CYCLE_WINDOW:
            progress.correct_count_in_cycle = 0
            progress.cycle_start_at = None
        if progress.cycle_start_at is None:
            progress.cycle_start_at = now
        progress.correct_count_in_cycle += 1
        if progress.status == "new":
            progress.status = "learning"

        if progress.correct_count_in_cycle >= REQUIRED_CORRECT_IN_CYCLE:
            progress.status = "learned"
            progress.learned_at = now
            progress.correct_count_in_cycle = 0
            progress.cycle_start_at = None
            progress.next_review_at = now + REINFORCEMENT_DELAY
        else:
            progress.next_review_at = now + CYCLE_INTERVALS[progress.correct_count_in_cycle]
    else:
        progress.total_wrong += 1
        progress.correct_count_in_cycle = 0
        progress.cycle_start_at = None
        progress.next_review_at = now + RETRY_SOON_DELAY

    await session.commit()
