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
