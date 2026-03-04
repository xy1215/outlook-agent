from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.main import _is_digest_stale, _should_backfill_push
from app.models import DailyDigest


class DummyStore:
    def __init__(self, state: Optional[dict] = None) -> None:
        self._state = state or {}

    def load(self) -> dict:
        return self._state


def test_is_digest_stale_true_when_date_mismatch():
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-03-03",
        tasks=[],
        important_mails=[],
        summary_text="x",
    )
    assert _is_digest_stale(digest, now) is True


def test_is_digest_stale_false_when_same_date():
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-03-04",
        tasks=[],
        important_mails=[],
        summary_text="x",
    )
    assert _is_digest_stale(digest, now) is False


def test_should_backfill_push_after_schedule_and_not_sent(monkeypatch):
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    monkeypatch.setattr("app.main.run_state_store", DummyStore({"last_push_date": "2026-03-03"}))
    assert _should_backfill_push(now) is True


def test_should_not_backfill_before_schedule(monkeypatch):
    now = datetime(2026, 3, 4, 6, 59, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    monkeypatch.setattr("app.main.run_state_store", DummyStore({"last_push_date": "2026-03-03"}))
    assert _should_backfill_push(now) is False


def test_should_not_backfill_when_already_sent_today(monkeypatch):
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    monkeypatch.setattr("app.main.run_state_store", DummyStore({"last_push_date": "2026-03-04"}))
    assert _should_backfill_push(now) is False
