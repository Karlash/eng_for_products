"""Word selection and answer recording.

Milestone 3 (current): plumbing only — random word selection, exact/normalized
string matching, simple total_correct/total_wrong counters. The full spaced-repetition
state machine (correct_count_in_cycle, learned/reinforcement transitions, due-review
scheduling) is added in milestone 4.
"""

import random
import re
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnswerLog, LearningProgress, Word, utcnow


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text)
    return text


async def pick_word_for_practice(session: AsyncSession) -> Word | None:
    words = (await session.execute(select(Word))).scalars().all()
    if not words:
        return None
    return random.choice(words)


def pick_direction() -> str:
    return random.choice(["en_to_ru", "ru_to_en"])


async def record_answer(
    session: AsyncSession,
    word: Word,
    direction: str,
    user_answer: str | None,
    was_correct: bool,
    judged_by: str,
    claude_explanation: str | None = None,
) -> None:
    session.add(
        AnswerLog(
            word_id=word.id,
            asked_at=utcnow(),
            direction=direction,
            user_answer=user_answer,
            was_correct=was_correct,
            judged_by=judged_by,
            claude_explanation=claude_explanation,
        )
    )
    progress = await session.scalar(select(LearningProgress).where(LearningProgress.word_id == word.id))
    if progress is not None:
        progress.last_asked_at = utcnow()
        if was_correct:
            progress.total_correct += 1
        else:
            progress.total_wrong += 1
    await session.commit()


def expected_answer(word: Word, direction: str) -> str:
    return word.russian if direction == "en_to_ru" else word.english


def judge_exact(word: Word, direction: str, user_answer: str) -> bool:
    return normalize(user_answer) == normalize(expected_answer(word, direction))
