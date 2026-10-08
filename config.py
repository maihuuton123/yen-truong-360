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
    max_report_images: int = Field(default=5, alias="MAX_REPORT_IMAGES")
    duplicate_detection_window_hours: int = Field(default=72, alias="DUPLICATE_DETECTION_WINDOW_HOURS")
    duplicate_similarity_threshold: float = Field(default=0.45, alias="DUPLICATE_SIMILARITY_THRESHOLD")
    duplicate_max_suggestions: int = Field(default=5, alias="DUPLICATE_MAX_SUGGESTIONS")
    public_report_rate_limit: int = Field(default=60, alias="PUBLIC_REPORT_RATE_LIMIT")
    public_report_rate_limit_window_seconds: int = Field(
        default=60,
        alias="PUBLIC_REPORT_RATE_LIMIT_WINDOW_SECONDS",
    )
    public_report_rapid_limit: int = Field(default=3, alias="PUBLIC_REPORT_RAPID_LIMIT")
    public_report_rapid_window_seconds: int = Field(default=10, alias="PUBLIC_REPORT_RAPID_WINDOW_SECONDS")
    public_report_spam_flag_threshold: int = Field(default=3, alias="PUBLIC_REPORT_SPAM_FLAG_THRESHOLD")
    public_report_captcha_risk_threshold: float = Field(default=0.7, alias="PUBLIC_REPORT_CAPTCHA_RISK_THRESHOLD")
    captcha_provider_enabled: bool = Field(default=False, alias="CAPTCHA_PROVIDER_ENABLED")
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
    trusted_proxy_ips: Annotated[list[str], NoDecode] = Field(default=[], alias="TRUSTED_PROXY_IPS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        return parse_string_list(value)

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def parse_trusted_proxy_ips(cls, value: str | list[str]) -> list[str]:
        return parse_string_list(value)


def parse_string_list(value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
