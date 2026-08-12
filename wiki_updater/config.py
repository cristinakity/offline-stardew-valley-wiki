from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LANGUAGES = ("en", "es", "de", "fr", "it", "ja", "ko", "hu", "pt", "ru", "tr", "zh")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_env: str = "local"
    data_dir: Path = Path(".local-data")
    database_path: Path | None = None
    local_auth_user: str = "developer"
    bind_host: str = "127.0.0.1"
    session_secret: str = "local-development-only-change-me"
    enabled: bool = True
    worker_enabled: bool = True
    builder_enabled: bool = True
    bootstrap_validation: str = "full"
    enabled_languages: tuple[str, ...] = LANGUAGES
    storage_limit_gb: int = Field(default=40, ge=1)
    min_free_gb: int = Field(default=30, ge=0)
    snapshot_retention: int = Field(default=3, ge=1, le=12)
    timezone: str = "America/Chicago"
    http_concurrency: int = Field(default=2, ge=1, le=2)
    page_concurrency: int = Field(default=2, ge=1, le=4)
    user_agent: str = "OfflineStardewValleyWiki/0.1 (contact configured by operator)"
    github_owner: str = "repository-owner"
    github_repository: str = "offline-stardew-valley-wiki"
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_allowed_users: tuple[str, ...] = ("operator",)

    @field_validator("enabled_languages", "oauth_allowed_users", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("enabled_languages")
    @classmethod
    def validate_languages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(LANGUAGES))
        if unknown:
            raise ValueError(f"Unsupported language codes: {', '.join(unknown)}")
        return value

    @field_validator("bootstrap_validation")
    @classmethod
    def validate_bootstrap_validation(cls, value: str) -> str:
        normalized = value.casefold()
        if normalized not in {"quick", "full"}:
            raise ValueError("BOOTSTRAP_VALIDATION must be quick or full.")
        return normalized

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        if self.database_path is None:
            self.database_path = self.data_dir / "updater.sqlite3"
        if self.app_env == "local" and self.bind_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local mode may only bind to a loopback address.")
        if self.app_env != "local":
            if not self.oauth_client_id or not self.oauth_client_secret:
                raise ValueError("Production requires GitHub OAuth credentials.")
            if len(self.session_secret) < 32:
                raise ValueError("Production SESSION_SECRET must contain at least 32 characters.")
        return self

    def ensure_directories(self) -> None:
        for name in ("blobs", "work", "snapshots", "candidates", "builds", "build-sources", "logs", "backups"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        assert self.database_path is not None
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
