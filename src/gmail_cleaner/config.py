"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = _SOURCE_ROOT if (_SOURCE_ROOT / "pyproject.toml").exists() else Path.cwd()


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    google_client_secret_file: Path
    google_token_file: Path
    database_path: Path
    max_messages_per_preview: int
    preview_ttl_minutes: int
    api_bearer_token: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        max_messages = int(os.getenv("MAX_MESSAGES_PER_PREVIEW", "200"))
        ttl = int(os.getenv("PREVIEW_TTL_MINUTES", "15"))
        if max_messages < 1 or max_messages > 1000:
            raise ValueError("MAX_MESSAGES_PER_PREVIEW must be between 1 and 1000.")
        if ttl < 1 or ttl > 120:
            raise ValueError("PREVIEW_TTL_MINUTES must be between 1 and 120.")
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            google_client_secret_file=_resolve_path(
                os.getenv("GOOGLE_CLIENT_SECRET_FILE", "credentials/client_secret.json")
            ),
            google_token_file=_resolve_path(
                os.getenv("GOOGLE_TOKEN_FILE", "credentials/token.json")
            ),
            database_path=_resolve_path(
                os.getenv("DATABASE_PATH", "data/gmail_cleaner.sqlite3")
            ),
            max_messages_per_preview=max_messages,
            preview_ttl_minutes=ttl,
            api_bearer_token=os.getenv("API_BEARER_TOKEN") or None,
        )
