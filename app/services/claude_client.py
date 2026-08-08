import anthropic
from pydantic import BaseModel

from app.config import settings

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None


class JudgeResult(BaseModel):
    correct: bool
    explanation: str


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
