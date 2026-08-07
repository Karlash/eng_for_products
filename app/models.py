from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime.datetime:
    # Naive UTC on purpose: SQLite has no real timezone-aware storage, so
    # SQLAlchemy always reads DateTime columns back as naive. Writing naive
    # values too keeps every comparison in this codebase apples-to-apples.
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    english: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    russian: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    part_of_speech: Mapped[str | None] = mapped_column(String(50), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)

    progress: Mapped["LearningProgress"] = relationship(
        back_populates="word", uselist=False, cascade="all, delete-orphan"
    )
    answers: Mapped[list["AnswerLog"]] = relationship(back_populates="word", cascade="all, delete-orphan")


class LearningProgress(Base):
    __tablename__ = "learning_progress"
    __table_args__ = (UniqueConstraint("word_id", name="uq_learning_progress_word_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")  # new | learning | learned
    correct_count_in_cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cycle_start_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    last_asked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    next_review_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True, index=True)
    learned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    total_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_wrong: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    word: Mapped["Word"] = relationship(back_populates="progress")


class AnswerLog(Base):
    __tablename__ = "answer_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=False)
    asked_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # en_to_ru | ru_to_en
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    was_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    judged_by: Mapped[str | None] = mapped_column(String(20), nullable=True)  # exact_match | normalized_match | claude
    claude_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    word: Mapped["Word"] = relationship(back_populates="answers")


class BotState(Base):
    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pending_word_id: Mapped[int | None] = mapped_column(ForeignKey("words.id"), nullable=True)
    pending_direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pending_asked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    pending_import_json: Mapped[str | None] = mapped_column(Text, nullable=True)
