from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import AnswerLog, LearningProgress, Word
from app.services.claude_client import ocr_extract_words
from app.services.dedup import filter_new_pairs

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PAGE_SIZE = 25


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/words")


SOURCE_LABELS = {
    "manual": "вручную",
    "imported_ocr": "импорт с фото",
    "suggested": "подобрано ботом",
}


@router.get("/words")
async def list_words(
    request: Request,
    status: str = "",
    topic: str = "",
    source: str = "",
    q: str = "",
    page: int = 1,
    session: AsyncSession = Depends(get_session),
):
    query = select(Word, LearningProgress).join(LearningProgress)
    if status:
        query = query.where(LearningProgress.status == status)
    if topic:
        query = query.where(Word.topic == topic)
    if source:
        query = query.where(Word.source == source)
    if q:
        like = f"%{q}%"
        query = query.where((Word.english.ilike(like)) | (Word.russian.ilike(like)))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))

    query = query.order_by(Word.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    rows = (await session.execute(query)).all()

    topics_result = await session.execute(select(Word.topic).distinct().where(Word.topic.is_not(None)))
    topics = sorted(t for (t,) in topics_result.all() if t)

    def qs(**overrides):
        params = {"status": status, "topic": topic, "source": source, "q": q, "page": page}
        params.update(overrides)
        params = {k: v for k, v in params.items() if v}
        return urlencode(params)

    return templates.TemplateResponse(
        request,
        "words_list.html",
        {
            "words": rows,
            "total": total,
            "topics": topics,
            "source_labels": SOURCE_LABELS,
            "status": status,
            "topic": topic,
            "source": source,
            "q": q,
            "page": page,
            "total_pages": total_pages,
            "qs": qs,
        },
    )


@router.get("/words/new")
async def new_word_form(request: Request):
    return templates.TemplateResponse(request, "word_form.html", {"form": None, "error": None})


@router.post("/words/new")
async def create_word(
    request: Request,
    english: str = Form(...),
    russian: str = Form(...),
    part_of_speech: str = Form(""),
    topic: str = Form(""),
    notes: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    english = english.strip()
    russian = russian.strip()
    if not english or not russian:
        return templates.TemplateResponse(
            request,
            "word_form.html",
            {"error": "English и Russian обязательны.", "form": {"english": english, "russian": russian, "part_of_speech": part_of_speech, "topic": topic, "notes": notes}},
        )

    word = Word(
        english=english,
        russian=russian,
        part_of_speech=part_of_speech or None,
        topic=topic.strip() or None,
        notes=notes.strip() or None,
        source="manual",
    )
    session.add(word)
    await session.flush()
    session.add(LearningProgress(word_id=word.id, status="new"))
    await session.commit()
    return RedirectResponse(url=f"/words/{word.id}", status_code=303)


@router.get("/words/{word_id}")
async def word_detail(request: Request, word_id: int, session: AsyncSession = Depends(get_session)):
    word = await session.get(Word, word_id)
    if word is None:
        return RedirectResponse(url="/words")
    progress = await session.scalar(select(LearningProgress).where(LearningProgress.word_id == word_id))
    answers = (
        await session.execute(
            select(AnswerLog).where(AnswerLog.word_id == word_id).order_by(AnswerLog.asked_at.desc())
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request, "word_detail.html", {"word": word, "progress": progress, "answers": answers}
    )


@router.get("/words/{word_id}/edit")
async def edit_word_form(request: Request, word_id: int, session: AsyncSession = Depends(get_session)):
    word = await session.get(Word, word_id)
    if word is None:
        return RedirectResponse(url="/words")
    return templates.TemplateResponse(request, "word_edit.html", {"word": word, "error": None})


@router.post("/words/{word_id}/edit")
async def edit_word(
    request: Request,
    word_id: int,
    english: str = Form(...),
    russian: str = Form(...),
    part_of_speech: str = Form(""),
    topic: str = Form(""),
    notes: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    word = await session.get(Word, word_id)
    if word is None:
        return RedirectResponse(url="/words")

    english = english.strip()
    russian = russian.strip()
    if not english or not russian:
        word.english, word.russian = english, russian
        return templates.TemplateResponse(
            request, "word_edit.html", {"word": word, "error": "English и Russian обязательны."}
        )

    word.english = english
    word.russian = russian
    word.part_of_speech = part_of_speech or None
    word.topic = topic.strip() or None
    word.notes = notes.strip() or None
    await session.commit()
    return RedirectResponse(url=f"/words/{word.id}", status_code=303)


@router.post("/words/{word_id}/delete")
async def delete_word(word_id: int, session: AsyncSession = Depends(get_session)):
    word = await session.get(Word, word_id)
    if word is not None:
        await session.delete(word)
        await session.commit()
    return RedirectResponse(url="/words", status_code=303)


@router.get("/import")
async def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", {"error": None})


@router.post("/import")
async def import_upload(
    request: Request,
    photo: UploadFile,
    session: AsyncSession = Depends(get_session),
):
    if not settings.anthropic_api_key:
        return templates.TemplateResponse(
            request, "import.html", {"error": "Импорт недоступен — не настроен Anthropic API-ключ."}
        )

    image_bytes = await photo.read()
    if not image_bytes:
        return templates.TemplateResponse(request, "import.html", {"error": "Файл пустой, попробуйте ещё раз."})

    try:
        extracted = await ocr_extract_words(image_bytes, photo.content_type or "image/jpeg")
    except Exception:
        return templates.TemplateResponse(
            request, "import.html", {"error": "Не удалось распознать слова на фото. Попробуйте другое фото."}
        )

    candidates = [(w.english, w.russian) for w in extracted]
    pos_by_english = {w.english.strip().lower(): (w.part_of_speech or "") for w in extracted}
    new_pairs = await filter_new_pairs(session, candidates)

    items = [
        {"english": en, "russian": ru, "part_of_speech": pos_by_english.get(en.strip().lower(), "")}
        for en, ru in new_pairs
    ]

    return templates.TemplateResponse(request, "import_preview.html", {"items": items})


@router.post("/import/confirm")
async def import_confirm(request: Request, session: AsyncSession = Depends(get_session)):
    form = await request.form()
    indices = sorted({key.split("_")[-1] for key in form.keys() if key.startswith("include_")})

    added = 0
    for idx in indices:
        english = (form.get(f"english_{idx}") or "").strip()
        russian = (form.get(f"russian_{idx}") or "").strip()
        part_of_speech = (form.get(f"part_of_speech_{idx}") or "").strip() or None
        if not english or not russian:
            continue
        word = Word(english=english, russian=russian, part_of_speech=part_of_speech, source="imported_ocr")
        session.add(word)
        await session.flush()
        session.add(LearningProgress(word_id=word.id, status="new"))
        added += 1

    await session.commit()
    return RedirectResponse(url="/words", status_code=303)


@router.get("/stats")
async def stats_page(request: Request, session: AsyncSession = Depends(get_session)):
    total_words = (await session.execute(select(func.count(Word.id)))).scalar_one()

    status_rows = (
        await session.execute(select(LearningProgress.status, func.count()).group_by(LearningProgress.status))
    ).all()
    status_counts = {"new": 0, "learning": 0, "learned": 0}
    status_counts.update({s: c for s, c in status_rows})

    topic_rows = (
        await session.execute(
            select(Word.topic, func.count()).group_by(Word.topic).order_by(func.count().desc())
        )
    ).all()

    total_correct = (await session.execute(select(func.sum(LearningProgress.total_correct)))).scalar() or 0
    total_wrong = (await session.execute(select(func.sum(LearningProgress.total_wrong)))).scalar() or 0

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "total_words": total_words,
            "status_counts": status_counts,
            "topic_counts": topic_rows,
            "total_correct": total_correct,
            "total_wrong": total_wrong,
        },
    )
