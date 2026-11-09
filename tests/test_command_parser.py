from gmail_cleaner.command_parser import RuleBasedCommandParser


SENDERS = [
    {"id": 1, "name": "Facebook", "email": "security@facebookmail.com"},
    {"id": 2, "name": "Infosys Springboard", "email": "springboard@infosys.com"},
    {"id": 3, "name": "Zoom", "email": "no-reply@zoom.us"},
]


def test_parse_multiple_known_sender_names():
    parsed = RuleBasedCommandParser().parse(
        "Delete all emails from Facebook and Zoom", SENDERS
    )
    assert parsed.intent == "preview_trash"
    assert parsed.senders == ["Facebook", "Zoom"]


def test_parse_explicit_email_not_in_sender_registry():
    parsed = RuleBasedCommandParser().parse(
        "Preview emails from alerts@example.com", SENDERS
    )
    assert parsed.senders == ["alerts@example.com"]


def test_parse_older_than_filter():
    parsed = RuleBasedCommandParser().parse(
        "delete emails from Zoom older than 90 days", SENDERS
    )
    assert parsed.older_than_days == 90
    assert parsed.senders == ["Zoom"]


def test_parse_absolute_date_filters():
    parsed = RuleBasedCommandParser().parse(
        "preview emails from Facebook after 2025-01-01 before 2025-06-01", SENDERS
    )
    assert parsed.after == "2025-01-01"
    assert parsed.before == "2025-06-01"


def test_parse_add_sender():
    parsed = RuleBasedCommandParser().parse(
        "add sender LinkedIn notifications@linkedin.com", SENDERS
    )
    assert parsed.intent == "add_sender"
    assert parsed.sender_name == "LinkedIn"
    assert parsed.sender_email == "notifications@linkedin.com"


def test_parse_remove_sender():
    parsed = RuleBasedCommandParser().parse(
        "remove sender Facebook from my sender list", SENDERS
    )
    assert parsed.intent == "remove_sender"
    assert parsed.sender_name == "Facebook"


def test_parse_list_senders():
    parsed = RuleBasedCommandParser().parse("list my senders", SENDERS)
    assert parsed.intent == "list_senders"


def test_unsupported_unread_filter_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="sender and date filters only"):
        RuleBasedCommandParser().parse("delete unread emails from Facebook", SENDERS)


def test_unsupported_inbox_filter_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="sender and date filters only"):
        RuleBasedCommandParser().parse("delete emails from Facebook in Inbox", SENDERS)
