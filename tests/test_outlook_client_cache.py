import asyncio
from datetime import datetime, timezone

from app.services.outlook_client import OutlookClient


class FakeOutlookClient(OutlookClient):
    def __init__(self):
        super().__init__(
            tenant_id="t",
            client_id="c",
            client_secret="s",
            user_email="u@example.com",
            redirect_uri="http://127.0.0.1/cb",
            token_store_path="data/test_token.json",
            cache_ttl_sec=600,
        )
        self.fetch_calls = 0

    async def _get_access_token(self):
        return "token"

    async def _fetch_messages_rows(self, token: str, max_count: int):
        self.fetch_calls += 1
        return [
            {
                "subject": f"Subject {max_count}",
                "from": {"emailAddress": {"address": "sender@example.com"}},
                "bodyPreview": "preview",
                "body": {"content": "<p>hello</p>"},
                "receivedDateTime": "2026-02-27T08:00:00Z",
                "importance": "high",
                "webLink": "https://example.com/mail",
            }
        ]


def test_fetch_recent_messages_uses_cache_by_default():
    client = FakeOutlookClient()

    first = asyncio.run(client.fetch_recent_messages(max_count=20))
    second = asyncio.run(client.fetch_recent_messages(max_count=20))

    assert len(first) == 1
    assert len(second) == 1
    assert client.fetch_calls == 1


def test_fetch_recent_messages_can_bypass_cache():
    client = FakeOutlookClient()

    _ = asyncio.run(client.fetch_recent_messages(max_count=20))
    _ = asyncio.run(client.fetch_recent_messages(max_count=20, use_cache=False))

    assert client.fetch_calls == 2


def test_strip_html_basic_cleanup():
    text = OutlookClient._strip_html("<p>A&nbsp;B<br>Line2 &amp; more</p>")
    assert text == "A B\nLine2 & more"
