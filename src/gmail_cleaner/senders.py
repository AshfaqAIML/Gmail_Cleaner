"""Sender validation and lookup helpers."""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

from .database import Database


def normalize_email(value: str) -> str:
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid sender email address: {value}") from exc


def add_sender(database: Database, name: str, email: str) -> dict:
    if not name.strip():
        raise ValueError("Provide a display name for the sender.")
    if len(name.strip()) > 120:
        raise ValueError("Sender name must be 120 characters or fewer.")
    return database.add_sender(name.strip(), normalize_email(email))


def resolve_sender_tokens(tokens: list[str], raw_command: str, known_senders: list[dict]) -> list[dict]:
    """Resolve model/parser output only against known names or literal user-supplied emails."""
    resolved: list[dict] = []
    raw_folded = raw_command.casefold()
    for token in tokens:
        value = token.strip().strip("\"'`.,;:<> ")
        if not value:
            continue
        match = next(
            (
                sender
                for sender in known_senders
                if value.casefold() in {sender["name"].casefold(), sender["email"].casefold()}
            ),
            None,
        )
        if match:
            # The model may resolve a name, but it must not add a sender the user
            # did not actually mention in the source command.
            if (
                match["name"].casefold() not in raw_folded
                and match["email"].casefold() not in raw_folded
            ):
                raise ValueError(
                    f"The parser selected '{match['name']}', but that sender was not "
                    "mentioned in your command. Nothing was searched."
                )
            resolved.append(match)
            continue
        if "@" in value:
            email = normalize_email(value)
            if email.casefold() not in raw_folded:
                raise ValueError(
                    f"The address {email} was not present in your command. "
                    "The agent will not use an address inferred by the AI."
                )
            resolved.append({"id": None, "name": email, "email": email})
            continue
        raise ValueError(
            f"I could not match '{value}' to your saved sender list. "
            "Add the sender first or use its exact email address in your command."
        )

    deduplicated: dict[str, dict] = {item["email"].casefold(): item for item in resolved}
    if not deduplicated:
        raise ValueError("Name at least one sender or include an exact sender email address.")
    return list(deduplicated.values())
