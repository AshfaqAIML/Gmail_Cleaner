"""Small SQLite persistence layer for senders and deletion previews."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_SENDERS = (
    ("Facebook", "security@facebookmail.com"),
    ("Infosys Springboard", "springboard@infosys.com"),
    ("Zoom", "no-reply@zoom.us"),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS senders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS previews (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    sender_emails_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    gmail_query TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT
                );
                """
            )
            seeded = connection.execute(
                "SELECT value FROM app_meta WHERE key = 'default_senders_seeded'"
            ).fetchone()
            if seeded is None:
                now = utc_now().isoformat()
                sender_count = connection.execute("SELECT COUNT(*) FROM senders").fetchone()[0]
                if sender_count == 0:
                    for name, email in DEFAULT_SENDERS:
                        connection.execute(
                            "INSERT OR IGNORE INTO senders(name, email, created_at) VALUES (?, ?, ?)",
                            (name, email, now),
                        )
                connection.execute(
                    "INSERT INTO app_meta(key, value) VALUES ('default_senders_seeded', 'true')"
                )

    def list_senders(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, email, created_at FROM senders ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_sender(self, name: str, email: str) -> dict[str, Any]:
        normalized_name = name.strip()
        normalized_email = email.strip().lower()
        if not normalized_name:
            raise ValueError("Sender name cannot be empty.")
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO senders(name, email, created_at) VALUES (?, ?, ?)",
                    (normalized_name, normalized_email, utc_now().isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "A sender with this name or email address already exists."
                ) from exc
            row = connection.execute(
                "SELECT id, name, email, created_at FROM senders WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def remove_sender(self, name_or_email: str) -> bool:
        value = name_or_email.strip()
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM senders WHERE email = ? COLLATE NOCASE OR name = ? COLLATE NOCASE",
                (value, value),
            )
        return cursor.rowcount > 0

    def create_preview(
        self,
        *,
        preview_id: str,
        command: str,
        sender_emails: list[str],
        payload: list[dict[str, str]],
        gmail_query: str,
        ttl_minutes: int,
    ) -> datetime:
        created = utc_now()
        expires = created + timedelta(minutes=ttl_minutes)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO previews
                (id, command, sender_emails_json, payload_json, gmail_query,
                 created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    preview_id,
                    command,
                    json.dumps(sender_emails),
                    json.dumps(payload),
                    gmail_query,
                    created.isoformat(),
                    expires.isoformat(),
                ),
            )
        return expires

    def get_preview(self, preview_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM previews WHERE id = ?", (preview_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["sender_emails"] = json.loads(result.pop("sender_emails_json"))
        result["payload"] = json.loads(result.pop("payload_json"))
        result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
        return result

    def claim_preview(self, preview_id: str) -> bool:
        """Atomically move a pending, unexpired preview to executing."""
        now = utc_now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE previews SET status = 'executing'
                   WHERE id = ? AND status = 'pending' AND expires_at > ?""",
                (preview_id, now),
            )
        return cursor.rowcount == 1

    def set_preview_status(self, preview_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE previews SET status = ?, result_json = ? WHERE id = ?",
                (status, json.dumps(result) if result is not None else None, preview_id),
            )

    def expire_preview(self, preview_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE previews SET status = 'expired' WHERE id = ? AND status = 'pending'",
                (preview_id,),
            )

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, command, sender_emails_json, gmail_query, created_at,
                          expires_at, status, result_json
                   FROM previews ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(limit, 200)),),
            ).fetchall()
        history = []
        for row in rows:
            item = dict(row)
            item["senders"] = json.loads(item.pop("sender_emails_json"))
            item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
            history.append(item)
        return history
