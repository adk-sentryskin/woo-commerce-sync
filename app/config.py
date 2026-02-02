from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    DB_DSN: str
    API_KEY: str
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8002
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    APP_URL: str
    ENCRYPTION_KEY: str
    ENABLE_SCHEDULER: bool = True
    RECONCILIATION_HOUR: int = 3
    RECONCILIATION_MINUTE: int = 0
    GCP_PROJECT_ID: Optional[str] = None
    GCP_REGION: str = "us-central1"
    ENABLE_EMBEDDINGS: bool = True
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    WC_API_VERSION: str = "wc/v3"
    WC_PRODUCTS_PER_PAGE: int = 100
    WC_REQUEST_TIMEOUT: int = 30
    WEBHOOK_SECRET_LENGTH: int = 32

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
