from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.env import BASE_DIR, load_project_env

load_project_env()


def _get_int_env(key: str, default: int) -> int:
    raw_value = os.getenv(key)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def _get_csv_env(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(key)
    if raw_value is None:
        return default

    values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return values or default


def _get_str_env(key: str, default: str) -> str:
    raw_value = os.getenv(key)
    if raw_value is None:
        return default

    normalized = raw_value.strip()
    return normalized or default


@dataclass(frozen=True,slots=True)
class Settings:
    app_name: str
    app_version: str
    api_v1_prefix: str
    database_filename: str
    storage_dirname: str
    storage_url_prefix: str
    public_base_url: str
    cors_origins: tuple[str, ...]
    ai_api_base_url: str
    ai_model_name: str
    ai_api_timeout: int

    @property
    def database_path(self) -> Path:
        return BASE_DIR / self.database_filename

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def storage_root(self) -> Path:
        return BASE_DIR / self.storage_dirname


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("JINGXIA_APP_NAME", "jingxia-core"),
        app_version=os.getenv("JINGXIA_APP_VERSION", "0.1.0"),
        api_v1_prefix=os.getenv("JINGXIA_API_V1_PREFIX", "/api/v1"),
        database_filename=os.getenv("JINGXIA_DATABASE_FILENAME", "jingxia.db"),
        storage_dirname=os.getenv("JINGXIA_STORAGE_DIRNAME", "storage"),
        storage_url_prefix=os.getenv("JINGXIA_STORAGE_URL_PREFIX", "/storage"),
        public_base_url=_get_str_env("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        cors_origins=_get_csv_env(
            "JINGXIA_CORS_ORIGINS",
            (
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:4173",
                "http://localhost:4173",
            ),
        ),
        ai_api_base_url=os.getenv("AI_API_BASE_URL", "http://localhost:8000/v1"),
        ai_model_name=os.getenv("AI_MODEL_NAME", "qwen-vl"),
        ai_api_timeout=_get_int_env("AI_API_TIMEOUT", 60),
    )


settings = get_settings()
