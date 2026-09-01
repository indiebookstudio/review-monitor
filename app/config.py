import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    APP_SECRET_KEY: str = Field(default="super-secret-key-replace-in-production-123456789")
    ADMIN_PASSWORD: str = Field(default="admin123")
    ADMIN_PASSWORD_HASH: str = Field(default="")
    
    DATABASE_URL: str = Field(default="sqlite:///./data/kdp_monitor.db")
    
    # Email & Notifications
    RESEND_API_KEY: str = Field(default="")
    SMTP_HOST: str = Field(default="smtp.gmail.com")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    ALERT_EMAIL: str = Field(default="saluccimarco@gmail.com")
    NOTIFICATIONS_ENABLED: bool = Field(default=True)
    
    DASHBOARD_URL: str = Field(default="http://localhost:8000")
    CHECK_FREQUENCY_HOURS: int = Field(default=24)
    AUTOMATIC_CHECKS_ENABLED: bool = Field(default=False)
    USE_PLAYWRIGHT_FALLBACK: bool = Field(default=False)
    
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
