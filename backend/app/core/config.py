"""Application settings loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4o"
    openai_reasoning_model: str = "gpt-4o"
    openai_tts_model: str = "tts-1"
    openai_tts_voice_male: str = "onyx"
    openai_tts_voice_female: str = "nova"

    database_url: str = "postgresql+psycopg://mathviz:mathviz@localhost:5432/mathviz"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "mathviz"
    s3_public_url: str = "http://127.0.0.1:9000"

    api_cors_origins: str = "http://localhost:3000"
    max_upload_mb: int = 25
    ocr_confidence_threshold: float = 0.75
    manim_max_attempts: int = 3
    manim_timeout_sec: int = 180
    default_user_email: str = "demo@mathviz.local"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
