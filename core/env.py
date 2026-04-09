from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def load_project_env() -> None:
    env_path = BASE_DIR / ".env"
    load_dotenv(env_path, override=False)
