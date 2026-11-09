from pathlib import Path

import pytest

from gmail_cleaner.command_parser import RuleBasedCommandParser
from gmail_cleaner.config import Settings
from gmail_cleaner.database import Database
from gmail_cleaner.models import EmailSummary
from gmail_cleaner.service import GmailCleanerService


class FakeGmailClient:
    def __init__(self, messages=None, fail_ids=None, mismatch_ids=None):
        self.messages = messages or []
        self.fail_ids = set(fail_ids or [])
        self.mismatch_ids = set(mismatch_ids or [])
        self.trashed = []
        self.last_query = None

    def search_messages(self, *, sender_emails, query, max_results):
        self.last_query = query
        return self.messages

    def verify_sender(self, message_id, allowed_senders):
        return (
            message_id not in self.mismatch_ids
            and "security@facebookmail.com" in allowed_senders
        )

    def move_to_trash(self, message_id):
        if message_id in self.fail_ids:
            raise RuntimeError("simulated Gmail error")
        self.trashed.append(message_id)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key=None,
        openai_model="gpt-5.5",
        google_client_secret_file=tmp_path / "client_secret.json",
        google_token_file=tmp_path / "token.json",
        database_path=tmp_path / "test.sqlite3",
        max_messages_per_preview=200,
        preview_ttl_minutes=15,
        api_bearer_token=None,
    )


def make_service(tmp_path: Path, messages=None, fail_ids=None, mismatch_ids=None):
    settings = make_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    fake_gmail = FakeGmailClient(
        messages=messages, fail_ids=fail_ids, mismatch_ids=mismatch_ids
    )
    service = GmailCleanerService(
        settings=settings,
        database=database,
        parser=RuleBasedCommandParser(),
        gmail_client=fake_gmail,
    )
    return service, database, fake_gmail


def sample_message(message_id="msg-1"):
    return EmailSummary(
        message_id=message_id,
        sender_name="Facebook Security",
        sender_email="security@facebookmail.com",
        subject="New login notification",
        date="Mon, 03 Nov 2025 10:00:00 +0000",
    )


def test_preview_does_not_trash_messages(tmp_path):
    service, database, gmail = make_service(tmp_path, [sample_message()])
    result = service.execute_command("preview emails from Facebook")
    assert result["status"] == "pending_confirmation"
    assert result["total_matches"] == 1
    assert gmail.trashed == []
    stored = database.get_preview(result["preview_id"])
    assert stored["status"] == "pending"
    assert stored["payload"][0]["message_id"] == "msg-1"


def test_confirm_moves_only_previewed_message_to_trash(tmp_path):
    service, _, gmail = make_service(tmp_path, [sample_message()])
    preview = service.execute_command("delete emails from Facebook")
    result = service.confirm_preview(preview["preview_id"], True)
    assert result["status"] == "completed"
    assert result["moved_to_trash"] == 1
    assert gmail.trashed == ["msg-1"]


def test_cancel_does_not_trash_messages(tmp_path):
    service, _, gmail = make_service(tmp_path, [sample_message()])
    preview = service.execute_command("preview emails from Facebook")
    result = service.confirm_preview(preview["preview_id"], False)
    assert result["status"] == "cancelled"
    assert gmail.trashed == []


def test_preview_cannot_be_reused(tmp_path):
    service, _, _ = make_service(tmp_path, [sample_message()])
    preview = service.execute_command("preview emails from Facebook")
    service.confirm_preview(preview["preview_id"], True)
    with pytest.raises(ValueError, match="status"):
        service.confirm_preview(preview["preview_id"], True)


def test_no_matches_creates_no_confirmation_preview(tmp_path):
    service, _, gmail = make_service(tmp_path, [])
    result = service.execute_command("preview emails from Facebook")
    assert result["status"] == "no_matches"
    assert result["preview_id"] is None
    assert gmail.trashed == []


def test_add_and_remove_sender(tmp_path):
    service, database, _ = make_service(tmp_path, [])
    added = service.execute_command("add sender LinkedIn notifications@linkedin.com")
    assert added["sender"]["email"] == "notifications@linkedin.com"
    assert any(item["name"] == "LinkedIn" for item in database.list_senders())
    removed = service.execute_command("remove sender LinkedIn from my sender list")
    assert removed["intent"] == "remove_sender"
    assert all(item["name"] != "LinkedIn" for item in database.list_senders())


def test_partial_failure_is_reported(tmp_path):
    service, _, gmail = make_service(
        tmp_path,
        [sample_message("msg-ok"), sample_message("msg-fail")],
        fail_ids={"msg-fail"},
    )
    preview = service.execute_command("preview emails from Facebook")
    result = service.confirm_preview(preview["preview_id"], True)
    assert result["status"] == "partially_completed"
    assert result["moved_to_trash"] == 1
    assert result["failed"] == 1
    assert gmail.trashed == ["msg-ok"]


def test_sender_is_revalidated_before_trash(tmp_path):
    service, _, gmail = make_service(
        tmp_path, [sample_message("msg-mismatch")], mismatch_ids={"msg-mismatch"}
    )
    preview = service.execute_command("preview emails from Facebook")
    result = service.confirm_preview(preview["preview_id"], True)
    assert result["status"] == "failed"
    assert result["moved_to_trash"] == 0
    assert gmail.trashed == []


def test_removed_default_sender_stays_removed_after_database_reinitialization(tmp_path):
    service, database, _ = make_service(tmp_path, [])
    service.execute_command("remove sender Facebook from my sender list")
    database.initialize()
    assert all(item["name"] != "Facebook" for item in database.list_senders())


def test_duplicate_sender_name_is_rejected(tmp_path):
    service, _, _ = make_service(tmp_path, [])
    with pytest.raises(ValueError, match="name or email"):
        service.execute_command("add sender Facebook other-facebook@example.com")
