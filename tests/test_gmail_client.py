from gmail_cleaner.gmail_client import GmailClient


class FakeRequest:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeMessages:
    def __init__(self, messages_by_id, search_result=None):
        self.messages_by_id = messages_by_id
        self.search_result = search_result or {}

    def list(self, **kwargs):
        return FakeRequest(self.search_result)

    def get(self, *, id, **kwargs):
        return FakeRequest(self.messages_by_id[id])


class FakeUsers:
    def __init__(self, messages):
        self._messages = messages

    def messages(self):
        return self._messages


class FakeService:
    def __init__(self, messages_by_id, search_result=None):
        self._messages = FakeMessages(messages_by_id, search_result)

    def users(self):
        return FakeUsers(self._messages)


def gmail_message(sender, subject="Test subject"):
    return {
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Mon, 03 Nov 2025 10:00:00 +0000"},
            ]
        }
    }


def test_search_filters_to_exact_from_address():
    service = FakeService(
        {
            "exact": gmail_message("Facebook Security <security@facebookmail.com>"),
            "alias": gmail_message("Facebook Security <alerts@facebookmail.com>"),
        },
        {"messages": [{"id": "exact"}, {"id": "alias"}]},
    )
    client = GmailClient(service)
    results = client.search_messages(
        sender_emails=["security@facebookmail.com"],
        query="from:security@facebookmail.com",
        max_results=200,
    )
    assert [item.message_id for item in results] == ["exact"]


def test_search_returns_sentinel_when_preview_cap_is_exceeded():
    message_ids = [{"id": f"m-{index}"} for index in range(201)]
    service = FakeService({}, {"messages": message_ids})
    client = GmailClient(service)
    results = client.search_messages(
        sender_emails=["security@facebookmail.com"],
        query="from:security@facebookmail.com",
        max_results=200,
    )
    assert len(results) == 1
    assert results[0].message_id == "__LIMIT_EXCEEDED__"


def test_verify_sender_rechecks_from_header():
    service = FakeService(
        {"m-1": gmail_message("Facebook Security <security@facebookmail.com>")}
    )
    client = GmailClient(service)
    assert client.verify_sender("m-1", ["security@facebookmail.com"]) is True
    assert client.verify_sender("m-1", ["other@example.com"]) is False
