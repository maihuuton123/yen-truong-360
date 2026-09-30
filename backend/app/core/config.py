import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Yen Truong 360", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str | None = Field(default=None, alias="ADMIN_PASSWORD")
    auth_secret_key: str | None = Field(default=None, alias="AUTH_SECRET_KEY")
    auth_token_expire_seconds: int = Field(default=3600, alias="AUTH_TOKEN_EXPIRE_SECONDS")
    upload_dir: str = Field(default="./uploads/reports", alias="UPLOAD_DIR")
    public_site_url: str = Field(default="http://localhost:5173", alias="PUBLIC_SITE_URL")
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    public_report_rate_limit: int = Field(default=10, alias="PUBLIC_REPORT_RATE_LIMIT")
    public_report_rate_limit_window_seconds: int = Field(
        default=60,
        alias="PUBLIC_REPORT_RATE_LIMIT_WINDOW_SECONDS",
    )
    public_lookup_rate_limit: int = Field(default=30, alias="PUBLIC_LOOKUP_RATE_LIMIT")
    public_lookup_rate_limit_window_seconds: int = Field(
        default=60,
        alias="PUBLIC_LOOKUP_RATE_LIMIT_WINDOW_SECONDS",
    )
    database_url: str = Field(
        default="sqlite:///./data/yen_truong_360.db",
        alias="DATABASE_URL",
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(origin).strip() for origin in parsed if str(origin).strip()]
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
