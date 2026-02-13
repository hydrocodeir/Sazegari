from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings loaded from environment variables (.env/.env.docker)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "سامانه سازگاری با کم‌آبی"
    ENV: str = "dev"

    # SECURITY
    SECRET_KEY: str = "CHANGE_ME"
    COOKIE_SECURE: bool = False   # set True behind HTTPS
    COOKIE_SAMESITE: str = "lax"
    SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 12  # 12h

    # CORS
    CORS_ALLOW_ORIGINS: str = "*"  # "*" or "https://a.com,https://b.com"
    CORS_ALLOW_CREDENTIALS: bool = False

    # DATABASE / CACHE
    MYSQL_DSN: str
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # UPLOADS
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_MB: int = 20

    # DEV BOOTSTRAP
    AUTO_CREATE_ADMIN: bool = True
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    DEFAULT_ADMIN_FULL_NAME: str = "Dev Admin"

    # SAMPLE DATA (for local testing)
    AUTO_SEED_SAMPLE: bool = False
    SAMPLE_SEED_PASSWORD: str = "123"

    def cors_origins(self) -> list[str]:
        s = (self.CORS_ALLOW_ORIGINS or "").strip()
        if not s or s == "*":
            return ["*"]
        return [x.strip() for x in s.split(",") if x.strip()]


settings = Settings()
