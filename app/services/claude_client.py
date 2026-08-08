import base64

import anthropic
from pydantic import BaseModel

from app.config import settings

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None


class JudgeResult(BaseModel):
    correct: bool
    explanation: str


class ExtractedWord(BaseModel):
    english: str
    russian: str
    part_of_speech: str | None = None


class OcrResult(BaseModel):
    words: list[ExtractedWord]


class SuggestedWord(BaseModel):
    english: str
    russian: str
    part_of_speech: str | None = None
    topic: str


class SuggestionResult(BaseModel):
    words: list[SuggestedWord]


async def judge_translation(word_english: str, word_russian: str, direction: str, user_answer: str) -> JudgeResult:
    expected = word_russian if direction == "en_to_ru" else word_english
    task = "переведи на русский" if direction == "en_to_ru" else "translate to English"

    prompt = (
        f"Слово: {word_english} (EN) / {word_russian} (RU).\n"
        f"Задание пользователю: {task}.\n"
        f"Ожидаемый ответ: {expected}\n"
        f"Ответ пользователя: {user_answer}\n\n"
        "Оцени, является ли ответ пользователя приемлемым переводом — учитывай синонимы, "
        "мелкие опечатки, альтернативные формулировки, артикли и регистр. "
        "Дай краткое (до 15 слов) объяснение на русском, полезное для изучающего язык."
    )

    response = await _client.messages.parse(
        model=settings.claude_model_judge,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
        output_format=JudgeResult,
    )
    return response.parsed_output


async def ocr_extract_words(image_bytes: bytes, media_type: str = "image/jpeg") -> list[ExtractedWord]:
    data = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = (
        "Это фото страницы бумажного англо-русского или русско-английского словаря. "
        "Извлеки все пары слово–перевод, которые видны на фото. "
        "Для каждой пары определи английское слово, русский перевод и часть речи "
        "(noun/verb/adjective/adverb/phrase/other), если она указана или очевидна из контекста. "
        "Игнорируй номера страниц, заголовки, транскрипцию в скобках и примеры использования — "
        "нужны только сами пары слово–перевод. Если слово написано с пометками или сокращениями "
        "части речи (n., v., adj.), используй их для определения part_of_speech."
    )

    response = await _client.messages.parse(
        model=settings.claude_model_ocr,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        output_format=OcrResult,
    )
    return response.parsed_output.words


async def suggest_new_words(
    existing_topics: list[str], sample_pairs: list[tuple[str, str]], batch_size: int
) -> list[SuggestedWord]:
    topics_str = ", ".join(existing_topics) if existing_topics else "пока нет данных"
    examples_str = (
        "\n".join(f"- {en} — {ru}" for en, ru in sample_pairs) if sample_pairs else "(словарь пока пуст)"
    )

    prompt = (
        "Ты помогаешь продакт-менеджеру в IT (уровень английского C1) пополнять словарный запас английского.\n"
        f"Основная тематика — Product Management и IT/технологии, плюс смежные темы, которые уже встречаются "
        f"в его словаре: {topics_str}.\n\n"
        f"Вот примеры слов, которые уже есть в словаре (не предлагай их снова и не предлагай синонимы, "
        f"дублирующие их по смыслу):\n{examples_str}\n\n"
        f"Предложи {batch_size} новых английских слов или устойчивых выражений уровня C1, полезных для "
        "продакт-менеджера в IT и смежных тем (аналитика, дизайн, финансы, коммуникация с бизнесом — по ситуации). "
        "Для каждого укажи русский перевод, часть речи (noun/verb/adjective/adverb/phrase/other) и короткую тему "
        "(topic) вида 'product-management', 'IT/tech' или другую релевантную метку. "
        "Избегай слишком базовой лексики (ниже уровня B2) и слов, уже упомянутых выше."
    )

    response = await _client.messages.parse(
        model=settings.claude_model_suggest,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
        output_format=SuggestionResult,
    )
    return response.parsed_output.words
