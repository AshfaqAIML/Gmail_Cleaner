import pytest

from gmail_cleaner.gmail_client import build_gmail_query
from gmail_cleaner.senders import resolve_sender_tokens


def test_single_sender_query():
    query = build_gmail_query(["security@facebookmail.com"], older_than_days=90)
    assert query == "from:security@facebookmail.com older_than:90d"


def test_multiple_senders_and_date_filters():
    query = build_gmail_query(
        ["no-reply@zoom.us", "security@facebookmail.com"],
        after="2025-01-01",
        before="2025-06-01",
        newer_than_days=30,
    )
    assert query == (
        "{from:no-reply@zoom.us from:security@facebookmail.com} "
        "after:2025/01/01 before:2025/06/01 newer_than:30d"
    )


def test_query_rejects_empty_sender_list():
    with pytest.raises(ValueError):
        build_gmail_query([])


def test_unrecognized_model_sender_is_rejected():
    registry = [{"id": 1, "name": "Facebook", "email": "security@facebookmail.com"}]
    with pytest.raises(ValueError, match="could not match"):
        resolve_sender_tokens(["Google"], "delete emails from Google", registry)


def test_model_cannot_invent_email_address():
    registry = []
    with pytest.raises(ValueError, match="not present in your command"):
        resolve_sender_tokens(["secret@example.com"], "delete emails from Facebook", registry)


def test_registered_sender_cannot_be_invented_by_parser():
    registry = [{"id": 1, "name": "Facebook", "email": "security@facebookmail.com"}]
    with pytest.raises(ValueError, match="not mentioned in your command"):
        resolve_sender_tokens(["Facebook"], "delete emails from Twitter", registry)
