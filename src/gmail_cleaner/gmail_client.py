"""Google OAuth and the narrow Gmail API operations used by the agent."""

from __future__ import annotations

import os
from email.utils import parseaddr
from typing import Any

from .config import Settings
from .models import EmailSummary
from .senders import normalize_email

# gmail.modify permits searching and moving messages to Trash. The app never
# calls the permanent-delete endpoint and does not request the full-mail scope.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def build_gmail_query(
    sender_emails: list[str],
    *,
    before: str | None = None,
    after: str | None = None,
    older_than_days: int | None = None,
    newer_than_days: int | None = None,
) -> str:
    """Build a Gmail search query exclusively from validated sender/date filters."""
    if not sender_emails:
        raise ValueError("At least one sender address is required.")
    normalized = sorted({normalize_email(email) for email in sender_emails})
    sender_terms = [f"from:{email}" for email in normalized]
    sender_clause = sender_terms[0] if len(sender_terms) == 1 else "{" + " ".join(sender_terms) + "}"
    parts = [sender_clause]
    if after:
        parts.append(f"after:{after.replace('-', '/')}")
    if before:
        parts.append(f"before:{before.replace('-', '/')}")
    if older_than_days:
        parts.append(f"older_than:{older_than_days}d")
    if newer_than_days:
        parts.append(f"newer_than:{newer_than_days}d")
    return " ".join(parts)


class GmailClient:
    def __init__(self, service: Any):
        self.service = service

    @classmethod
    def from_settings(cls, settings: Settings) -> "GmailClient":
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google API dependencies are missing. Install the project with: pip install -e ."
            ) from exc

        client_secret = settings.google_client_secret_file
        token_file = settings.google_token_file
        if not client_secret.exists():
            raise FileNotFoundError(
                f"Google OAuth client file not found: {client_secret}. "
                "Download the Desktop app OAuth JSON from Google Cloud and place it there."
            )

        token_file.parent.mkdir(parents=True, exist_ok=True)
        credentials = None
        if token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(token_file), GMAIL_SCOPES)
            if not credentials.has_scopes(GMAIL_SCOPES):
                credentials = None

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_file.write_text(credentials.to_json(), encoding="utf-8")
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), GMAIL_SCOPES)
            credentials = flow.run_local_server(
                host="localhost",
                port=0,
                access_type="offline",
                prompt="consent",
            )
            token_file.write_text(credentials.to_json(), encoding="utf-8")
            try:
                os.chmod(token_file, 0o600)
            except OSError:
                # Windows does not implement POSIX permission bits in the same way.
                pass

        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return cls(service)

    def search_messages(
        self,
        *,
        sender_emails: list[str],
        query: str,
        max_results: int,
    ) -> list[EmailSummary]:
        """Search up to max_results + 1 exact-sender matches; cap overflow safely."""
        response = self.service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(500, max_results + 1),
            includeSpamTrash=False,
        ).execute()
        message_ids = [item["id"] for item in (response.get("messages") or [])]
        next_page_token = response.get("nextPageToken")
        while next_page_token and len(message_ids) < max_results + 1:
            response = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=min(500, max_results + 1 - len(message_ids)),
                pageToken=next_page_token,
                includeSpamTrash=False,
            ).execute()
            message_ids.extend(item["id"] for item in (response.get("messages") or []))
            next_page_token = response.get("nextPageToken")

        if len(message_ids) > max_results:
            return [
                EmailSummary(
                    message_id="__LIMIT_EXCEEDED__",
                    sender_name="",
                    sender_email="",
                    subject="",
                    date="",
                )
            ]

        requested = {normalize_email(item) for item in sender_emails}
        summaries: list[EmailSummary] = []
        for message_id in message_ids:
            message = self.service.users().messages().get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {
                item.get("name", "").casefold(): item.get("value", "")
                for item in message.get("payload", {}).get("headers", [])
            }
            display_name, from_address = parseaddr(headers.get("from", ""))
            try:
                sender_email = normalize_email(from_address)
            except ValueError:
                continue
            # Gmail's search operator can match aliases/display names. Only keep an
            # exact RFC 5322 From address match to prevent an overly broad result.
            if sender_email not in requested:
                continue
            summaries.append(
                EmailSummary(
                    message_id=message_id,
                    sender_name=display_name or sender_email,
                    sender_email=sender_email,
                    subject=headers.get("subject", "(no subject)"),
                    date=headers.get("date", ""),
                )
            )
        return summaries

    def verify_sender(self, message_id: str, allowed_senders: list[str]) -> bool:
        """Re-fetch the From header immediately before a destructive action."""
        message = self.service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From"],
        ).execute()
        headers = {
            item.get("name", "").casefold(): item.get("value", "")
            for item in message.get("payload", {}).get("headers", [])
        }
        _, from_address = parseaddr(headers.get("from", ""))
        try:
            actual_sender = normalize_email(from_address)
        except ValueError:
            return False
        allowed = {normalize_email(item) for item in allowed_senders}
        return actual_sender in allowed

    def move_to_trash(self, message_id: str) -> None:
        self.service.users().messages().trash(userId="me", id=message_id).execute()


def authenticate(settings: Settings) -> None:
    """Perform OAuth once and print no credentials or token contents."""
    GmailClient.from_settings(settings)
