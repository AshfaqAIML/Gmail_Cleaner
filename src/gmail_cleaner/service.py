"""Application orchestration: parse, validate, preview, then confirm."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .command_parser import CommandParser
from .config import Settings
from .database import Database
from .gmail_client import GmailClient, build_gmail_query
from .models import ConfirmationResult, PreviewResult, SenderCreate
from .senders import add_sender, resolve_sender_tokens


class GmailCleanerService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        parser: CommandParser,
        gmail_client: GmailClient | None = None,
    ):
        self.settings = settings
        self.database = database
        self.parser = parser
        self._gmail_client = gmail_client

    @property
    def gmail(self) -> GmailClient:
        if self._gmail_client is None:
            self._gmail_client = GmailClient.from_settings(self.settings)
        return self._gmail_client

    def execute_command(self, command: str) -> dict[str, Any]:
        known_senders = self.database.list_senders()
        parsed = self.parser.parse(command, known_senders)

        if parsed.intent == "help":
            return {
                "intent": "help",
                "commands": [
                    "Preview: delete emails from Facebook and Zoom",
                    "Date filter: preview emails from Zoom older than 90 days",
                    "Add: add sender LinkedIn notifications@linkedin.com",
                    "Remove: remove sender Facebook from my sender list",
                    "List: list my senders",
                ],
            }
        if parsed.intent == "list_senders":
            return {"intent": "list_senders", "senders": self.database.list_senders()}
        if parsed.intent == "add_sender":
            if not parsed.sender_name or not parsed.sender_email:
                raise ValueError("Use: add sender NAME EMAIL_ADDRESS")
            if parsed.sender_name.casefold() not in command.casefold():
                raise ValueError("The sender name must be stated explicitly in your command.")
            if parsed.sender_email.casefold() not in command.casefold():
                raise ValueError("The sender email must be stated explicitly in your command.")
            sender = add_sender(self.database, parsed.sender_name, parsed.sender_email)
            return {"intent": "add_sender", "sender": sender}
        if parsed.intent == "remove_sender":
            if not parsed.sender_name:
                raise ValueError("Name the saved sender to remove.")
            if parsed.sender_name.casefold() not in command.casefold():
                raise ValueError("The sender to remove must be named explicitly in your command.")
            if not any(term in command.casefold() for term in ("sender list", "saved sender", "senders list")):
                raise ValueError("To remove a rule, say 'remove sender NAME from my sender list'.")
            removed = self.database.remove_sender(parsed.sender_name)
            if not removed:
                raise ValueError(f"No saved sender named '{parsed.sender_name}' was found.")
            return {"intent": "remove_sender", "removed": parsed.sender_name}
        if parsed.intent != "preview_trash":
            raise ValueError("Unsupported command.")

        resolved = resolve_sender_tokens(parsed.senders, command, known_senders)
        sender_emails = [item["email"] for item in resolved]
        query = build_gmail_query(
            sender_emails,
            before=parsed.before,
            after=parsed.after,
            older_than_days=parsed.older_than_days,
            newer_than_days=parsed.newer_than_days,
        )
        matches = self.gmail.search_messages(
            sender_emails=sender_emails,
            query=query,
            max_results=self.settings.max_messages_per_preview,
        )
        if any(item.message_id == "__LIMIT_EXCEEDED__" for item in matches):
            raise ValueError(
                f"More than {self.settings.max_messages_per_preview} messages matched. "
                "No preview was created and nothing was changed. Add a date filter or use a smaller group of senders."
            )

        if not matches:
            return PreviewResult(
                status="no_matches",
                preview_id=None,
                total_matches=0,
                senders=sender_emails,
                gmail_query=query,
                expires_at=None,
                messages=[],
                note="No matching messages were found. Nothing was changed.",
            ).model_dump(mode="json")

        preview_id = str(uuid.uuid4())
        payload = [item.model_dump(mode="json") for item in matches]
        expires_at = self.database.create_preview(
            preview_id=preview_id,
            command=command,
            sender_emails=sender_emails,
            payload=payload,
            gmail_query=query,
            ttl_minutes=self.settings.preview_ttl_minutes,
        )
        return PreviewResult(
            status="pending_confirmation",
            preview_id=preview_id,
            total_matches=len(matches),
            senders=sender_emails,
            gmail_query=query,
            expires_at=expires_at,
            messages=matches,
            note=(
                "Review these results. No messages have been moved. Confirm this exact preview "
                "before it expires to move these messages to Gmail Trash."
            ),
        ).model_dump(mode="json")

    def confirm_preview(self, preview_id: str, confirm: bool) -> dict[str, Any]:
        preview = self.database.get_preview(preview_id)
        if preview is None:
            raise ValueError("Preview not found. It may have expired or the ID may be invalid.")
        if preview["status"] != "pending":
            raise ValueError(f"This preview cannot be used because its status is '{preview['status']}'.")

        expires_at = datetime.fromisoformat(preview["expires_at"])
        if expires_at <= datetime.now(timezone.utc):
            self.database.expire_preview(preview_id)
            raise ValueError("This preview has expired. Run the search again to create a new preview.")

        if not confirm:
            self.database.set_preview_status(preview_id, "cancelled", {"moved_to_trash": 0})
            return ConfirmationResult(
                status="cancelled",
                preview_id=preview_id,
                requested=len(preview["payload"]),
                moved_to_trash=0,
                failed=0,
                note="Cancelled. No messages were changed.",
            ).model_dump(mode="json")

        if not self.database.claim_preview(preview_id):
            raise ValueError("This preview was already used, expired, or is being processed.")

        moved = 0
        errors: list[str] = []
        for item in preview["payload"]:
            try:
                if not self.gmail.verify_sender(item["message_id"], preview["sender_emails"]):
                    raise ValueError("From address no longer matches the previewed sender rule")
                self.gmail.move_to_trash(item["message_id"])
                moved += 1
            except Exception as exc:  # keep processing other selected messages
                errors.append(f"{item['message_id']}: {type(exc).__name__}")

        requested = len(preview["payload"])
        failed = requested - moved
        if failed == 0:
            status = "completed"
            db_status = "completed"
        elif moved == 0:
            status = "failed"
            db_status = "failed"
        else:
            status = "partially_completed"
            db_status = "partially_completed"

        result = {
            "status": status,
            "requested": requested,
            "moved_to_trash": moved,
            "failed": failed,
            "errors": errors,
        }
        self.database.set_preview_status(preview_id, db_status, result)
        return ConfirmationResult(
            status=status,
            preview_id=preview_id,
            requested=requested,
            moved_to_trash=moved,
            failed=failed,
            errors=errors,
            note=(
                "Selected messages were moved to Gmail Trash."
                if failed == 0
                else "Some messages could not be moved. Check the error summary and Gmail before retrying."
            ),
        ).model_dump(mode="json")

    def add_sender(self, body: SenderCreate) -> dict[str, Any]:
        return add_sender(self.database, body.name, str(body.email))
