import asyncio

from sqlalchemy import select

from app.db import async_session, init_db
from app.models import LearningProgress, Word

SEED_WORDS = [
    ("stakeholder", "заинтересованная сторона", "noun", "product-management"),
    ("roadmap", "дорожная карта", "noun", "product-management"),
    ("backlog", "бэклог", "noun", "product-management"),
    ("trade-off", "компромисс", "noun", "product-management"),
    ("churn", "отток клиентов", "noun", "product-management"),
    ("edge case", "крайний случай", "noun", "IT/tech"),
    ("rollout", "постепенный запуск", "noun", "product-management"),
    ("scalability", "масштабируемость", "noun", "IT/tech"),
    ("latency", "задержка", "noun", "IT/tech"),
    ("throughput", "пропускная способность", "noun", "IT/tech"),
]


async def seed() -> None:
    await init_db()
    async with async_session() as session:
        for english, russian, pos, topic in SEED_WORDS:
            existing = await session.scalar(select(Word).where(Word.english == english))
            if existing:
                continue
            word = Word(english=english, russian=russian, part_of_speech=pos, topic=topic, source="manual")
            session.add(word)
            await session.flush()
            session.add(LearningProgress(word_id=word.id, status="new"))
        await session.commit()
    print(f"Seeded {len(SEED_WORDS)} words (skipping duplicates).")


if __name__ == "__main__":
    asyncio.run(seed())
