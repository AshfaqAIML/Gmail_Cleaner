"""Natural-language command parsing with a safe deterministic fallback."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Protocol

from .models import ParsedCommand

EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
UNSUPPORTED_FILTER_PATTERNS = (
    r"\bunread\b",
    r"\bread\s+(?:emails?|messages?)\b",
    r"\bin\s+(?:the\s+)?inbox\b",
    r"\barchived?\b",
    r"\b(?:has:attachment|attachments?)\b",
    r"\b(?:subject|body|content)\b",
    r"\b(?:contains?|containing|keyword|phrase)\b",
    r"\b(?:that\s+say|that\s+mention|with\s+the\s+word)\b",
    r"\bstarred\b",
    r"\blabel:",
    r"\b(?:subject|to|cc|bcc|has|older_than|newer_than|after|before|category|filename|larger|smaller):",
    r"\binbox\s+only\b",
    r"\bis:[a-z_-]+",
    r"\b(?:exclude|excluding|except|but\s+not)\b",
    r"\bnot\s+from\b",
    r"\b(?:latest|newest|oldest)\s+\d+\b",
    r"\b(?:today|yesterday|since|during|between|this\s+week|last\s+week|this\s+month|last\s+month|this\s+year|last\s+year|this\s+weekend|last\s+weekend|this\s+morning|this\s+afternoon|this\s+evening)\b",
)


class CommandParser(Protocol):
    def parse(self, command: str, known_senders: list[dict]) -> ParsedCommand: ...


class RuleBasedCommandParser:
    """A predictable parser used when no model key is configured or the API fails."""

    def parse(self, command: str, known_senders: list[dict]) -> ParsedCommand:
        text = command.strip()
        lowered = text.casefold()
        if not text:
            raise ValueError("Enter a command.")

        add_match = re.search(
            r"\badd\s+(?:a\s+)?sender\s+(.+?)\s*[<\[]?"
            r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})[>\]]?\s*$",
            text,
            re.IGNORECASE,
        )
        if add_match:
            name = add_match.group(1).strip(" \"'`:-")
            return ParsedCommand(
                intent="add_sender", sender_name=name, sender_email=add_match.group(2).lower()
            )

        remove_match = re.search(
            r"\b(?:remove|delete)\s+sender\s+(.+?)\s+(?:from\s+)?(?:my\s+)?(?:saved\s+)?(?:sender\s+)?list\s*$",
            text,
            re.IGNORECASE,
        )
        if remove_match:
            return ParsedCommand(intent="remove_sender", sender_name=remove_match.group(1).strip())

        if re.search(r"\b(list|show)\b.*\bsenders?\b", lowered):
            return ParsedCommand(intent="list_senders")
        if lowered in {"help", "what can you do?", "commands"}:
            return ParsedCommand(intent="help")

        unsupported = [
            pattern for pattern in UNSUPPORTED_FILTER_PATTERNS
            if re.search(pattern, lowered, re.IGNORECASE)
        ]
        if unsupported:
            raise ValueError(
                "This version supports sender and date filters only. I detected an additional "
                "condition that is not supported, so no Gmail search was run."
            )

        if not re.search(r"\b(delete|trash|remove|clean|show|find|preview)\b", lowered):
            raise ValueError(
                "I can preview sender-based email cleanup, manage saved senders, or list senders. "
                "Try: 'preview emails from Facebook'."
            )

        sender_tokens: list[str] = []
        for sender in known_senders:
            if re.search(rf"(?<![\w]){re.escape(sender['name'])}(?![\w])", text, re.IGNORECASE):
                sender_tokens.append(sender["name"])
        sender_tokens.extend(match.group(0).lower() for match in EMAIL_PATTERN.finditer(text))

        before = self._extract_date(text, "before")
        after = self._extract_date(text, "after")
        older = self._extract_day_count(text, r"older\s+than\s+(\d+)\s+days?")
        newer = self._extract_day_count(
            text, r"(?:within\s+the\s+last|in\s+the\s+last|over\s+the\s+last|for\s+the\s+last|past|newer\s+than|last)\s+(\d+)\s+days?"
        )
        if before and after and before <= after:
            raise ValueError("The 'before' date must be later than the 'after' date.")

        return ParsedCommand(
            intent="preview_trash",
            senders=sender_tokens,
            before=before,
            after=after,
            older_than_days=older,
            newer_than_days=newer,
        )

    @staticmethod
    def _extract_date(text: str, operator: str) -> str | None:
        match = re.search(rf"\b{operator}\s+(\d{{4}}-\d{{2}}-\d{{2}})\b", text, re.IGNORECASE)
        if not match:
            return None
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid {operator} date. Use YYYY-MM-DD.") from exc

    @staticmethod
    def _extract_day_count(text: str, pattern: str) -> int | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        days = int(match.group(1))
        if not 1 <= days <= 3650:
            raise ValueError("Date windows must be between 1 and 3650 days.")
        return days


class OpenAICommandParser:
    """Uses Structured Outputs for intent extraction; never receives Gmail credentials."""

    SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["preview_trash", "add_sender", "remove_sender", "list_senders", "help"],
            },
            "senders": {"type": "array", "items": {"type": "string"}},
            "unsupported_conditions": {"type": "array", "items": {"type": "string"}},
            "sender_name": {"type": ["string", "null"]},
            "sender_email": {"type": ["string", "null"]},
            "before": {"type": ["string", "null"]},
            "after": {"type": ["string", "null"]},
            "older_than_days": {"type": ["integer", "null"]},
            "newer_than_days": {"type": ["integer", "null"]},
        },
        "required": [
            "intent", "senders", "unsupported_conditions", "sender_name", "sender_email", "before", "after",
            "older_than_days", "newer_than_days",
        ],
    }

    def __init__(self, api_key: str, model: str, fallback: CommandParser | None = None):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.fallback = fallback or RuleBasedCommandParser()

    def parse(self, command: str, known_senders: list[dict]) -> ParsedCommand:
        system = (
            "You translate a user's Gmail-cleanup request into a restricted command schema. "
            "Never invent an email address. For deletion, identify only sender names or literal "
            "email addresses present in the user's command. Saved sender names are supplied below. "
            "Only interpret date filters explicitly stated by the user. Do not call tools, access Gmail, "
            "or decide that deletion is already approved. Every email cleanup request is preview-only. "
            "For add_sender, extract the exact name and email the user supplied. For remove_sender, "
            "extract the saved sender name. If ambiguous, use help. If the user includes any filter "
            "other than sender or date filters supported by the schema (for example unread/read, inbox, "
            "attachments, labels, starred, exclusions, relative periods other than day counts, or a result "
            "limit), put a description in unsupported_conditions. Never silently drop a condition."
        )
        user = json.dumps(
            {
                "saved_senders": [
                    {"name": item["name"], "email": item["email"]} for item in known_senders
                ],
                "command": command,
            }
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "gmail_cleanup_command",
                        "strict": True,
                        "schema": self.SCHEMA,
                    }
                },
            )
            parsed = ParsedCommand.model_validate(json.loads(response.output_text))
        except Exception:
            # Deterministic parsing keeps the app usable if the model is unavailable.
            return self.fallback.parse(command, known_senders)

        if parsed.unsupported_conditions:
            raise ValueError(
                "This version supports sender and date filters only. Unsupported condition(s): "
                + ", ".join(parsed.unsupported_conditions)
                + ". No Gmail search was run."
            )

        try:
            # A model is not allowed to smuggle in an address absent from the user's text.
            for value in parsed.senders:
                if "@" in value and value.casefold() not in command.casefold():
                    raise ValueError("The AI returned an email address that was not in the command.")
            if parsed.sender_email and parsed.sender_email.casefold() not in command.casefold():
                raise ValueError("The AI returned an email address that was not in the command.")
            for operator, value in (("before", parsed.before), ("after", parsed.after)):
                if value and not re.search(
                    rf"\b{operator}\s+{re.escape(value)}\b", command, re.IGNORECASE
                ):
                    raise ValueError(f"The AI inferred a {operator} date not stated in the command.")
            if parsed.older_than_days and not re.search(
                rf"\bolder\s+than\s+{parsed.older_than_days}\s+days?\b", command, re.IGNORECASE
            ):
                raise ValueError("The AI inferred an older-than filter not stated in the command.")
            if parsed.newer_than_days and not re.search(
                rf"\b(?:within\s+the\s+last|in\s+the\s+last|over\s+the\s+last|for\s+the\s+last|past|newer\s+than|last)\s+{parsed.newer_than_days}\s+days?\b",
                command,
                re.IGNORECASE,
            ):
                raise ValueError("The AI inferred a newer-than filter not stated in the command.")
            return parsed
        except Exception:
            return self.fallback.parse(command, known_senders)


def build_parser(api_key: str | None, model: str) -> CommandParser:
    fallback = RuleBasedCommandParser()
    if not api_key:
        return fallback
    return OpenAICommandParser(api_key=api_key, model=model, fallback=fallback)
