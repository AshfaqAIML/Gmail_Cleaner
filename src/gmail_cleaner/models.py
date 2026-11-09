"""Typed models shared by the API, parser and service layer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class Sender(BaseModel):
    id: int
    name: str
    email: EmailStr
    created_at: datetime


class SenderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr


class ParsedCommand(BaseModel):
    """A restricted intent; it is never an executable Gmail API instruction."""

    model_config = ConfigDict(extra="forbid")
    intent: Literal["preview_trash", "add_sender", "remove_sender", "list_senders", "help"]
    senders: list[str] = Field(default_factory=list)
    unsupported_conditions: list[str] = Field(default_factory=list)
    sender_name: str | None = None
    sender_email: str | None = None
    before: str | None = None
    after: str | None = None
    older_than_days: int | None = Field(default=None, ge=1, le=3650)
    newer_than_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("before", "after")
    @classmethod
    def validate_iso_dates(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from datetime import date

        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError("Date filters must use YYYY-MM-DD format.") from exc

    @model_validator(mode="after")
    def validate_date_order(self) -> "ParsedCommand":
        if self.before and self.after and self.before <= self.after:
            raise ValueError("The 'before' date must be later than the 'after' date.")
        return self


class EmailSummary(BaseModel):
    message_id: str
    sender_name: str
    sender_email: str
    subject: str
    date: str


class PreviewResult(BaseModel):
    status: Literal["pending_confirmation", "no_matches"]
    preview_id: str | None
    total_matches: int
    senders: list[str]
    gmail_query: str
    expires_at: datetime | None
    messages: list[EmailSummary]
    note: str


class ConfirmationRequest(BaseModel):
    preview_id: str
    confirm: bool


class ConfirmationResult(BaseModel):
    status: Literal["completed", "partially_completed", "failed", "cancelled"]
    preview_id: str
    requested: int
    moved_to_trash: int
    failed: int
    errors: list[str] = Field(default_factory=list)
    note: str
