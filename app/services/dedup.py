from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Word


async def filter_new_pairs(
    session: AsyncSession, candidates: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Drop candidates that duplicate an existing word (by english or russian, case-insensitive)."""
    existing_rows = (await session.execute(select(Word.english, Word.russian))).all()
    existing: set[str] = set()
    for en, ru in existing_rows:
        existing.add(en.strip().lower())
        existing.add(ru.strip().lower())

    result: list[tuple[str, str]] = []
    seen_in_batch: set[str] = set()
    for english, russian in candidates:
        key_en = english.strip().lower()
        key_ru = russian.strip().lower()
        if not key_en or not key_ru:
            continue
        if key_en in existing or key_ru in existing:
            continue
        if key_en in seen_in_batch or key_ru in seen_in_batch:
            continue
        seen_in_batch.add(key_en)
        seen_in_batch.add(key_ru)
        result.append((english.strip(), russian.strip()))

    return result
