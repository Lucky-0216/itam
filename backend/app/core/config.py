from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_NAME: str = "ITAM 资产管理系统"
    APP_VERSION: str = "0.1.0"
    APP_ENV: Literal["development", "test", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    SECRET_KEY: str = "itam-dev-secret-please-change-me-32bytes"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    TOKEN_STORE: Literal["redis", "memory"] = "redis"
    REDIS_URL: str = "redis://redis:6379/0"

    DB_HOST: str = "mysql"
    DB_PORT: int = 3306
    DB_USER: str = "itam"
    DB_PASSWORD: str = "itam"
    DB_NAME: str = "itam"
    DB_ECHO: bool = False
    DATABASE_URL: str | None = None

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = ""
    DEFAULT_ADMIN_NAME: str = "系统管理员"
    DEFAULT_USER_PASSWORD: str = ""
    UPLOAD_DIR: str = "/app/uploads"
    ASSET_NO_PREFIX: str = "ITAM"
    ASSET_NO_PATTERN: str = "{prefix}-{year}{month}-{seq:04d}"
    # 仅用于本地演示/测试：写入示例部门、分类、型号；生产保持 false
    SEED_SAMPLE_DATA: bool = False

    WARRANTY_REMINDER_DAYS: int = 30
    CONTRACT_REMINDER_DAYS: int = 30
    BORROW_REMINDER_DAYS: int = 3
    INVENTORY_REMINDER_DAYS: int = 3

    REMINDER_EMAIL_ENABLED: bool = False
    REMINDER_EMAIL_TO: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    @property
    def sqlalchemy_dsn(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"mysql+aiomysql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
