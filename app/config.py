from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vocab.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_user_id: int = 0

    database_url: str = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"

    timezone: str = "Europe/Moscow"
    schedule_times: str = "09:00,14:00,20:00"
    max_new_words_per_day: int = 3

    suggestion_threshold: int = 15
    suggestion_batch_size: int = 20
    suggestion_schedule_day: str = "sun"
    suggestion_schedule_time: str = "10:00"

    claude_model_ocr: str = "claude-sonnet-5"
    claude_model_judge: str = "claude-haiku-4-5-20251001"
    claude_model_suggest: str = "claude-sonnet-5"

    @property
    def schedule_times_list(self) -> list[str]:
        return [t.strip() for t in self.schedule_times.split(",") if t.strip()]


settings = Settings()
