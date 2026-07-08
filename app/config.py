from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 1

    # Groq AI
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Payment (Kaspi phone number instead of API)
    PAYMENT_KASPI_PHONE: str = "+77001234567"
    PAYMENT_DESCRIPTION: str = "Оплата за публикацию приглашения"

    # File storage (local)
    MEDIA_DIR: str = "media/uploads"
    MEDIA_THUMBS_DIR: str = "media/thumbs"
    MAX_FILE_SIZE_MB: int = 5

    # Logging
    LOGS_DIR: str = "logs"

    # App
    ENVIRONMENT: str = "development"
    FRONTEND_VERCEL: str = "http://localhost:3000"
    FRONTEND_HOSTING: str = "https://www.invitation.kz/"
    MEDIA_BASE_URL: str = "/media"


settings = Settings()
