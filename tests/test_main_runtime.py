from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.main import _should_backfill_push


class DummyStore:
    def __init__(self, state: dict | None = None) -> None:
        self._state = state or {}

    def load(self) -> dict:
        return self._state


def test_should_backfill_push_after_schedule_and_not_sent(monkeypatch):
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    # last_success_at is from the previous day in LA timezone
    monkeypatch.setattr("app.main.run_state_store", DummyStore({"last_success_at": "2026-03-03T15:00:00-08:00"}))
    assert _should_backfill_push(now) is True


def test_should_not_backfill_before_schedule(monkeypatch):
    now = datetime(2026, 3, 4, 6, 59, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    monkeypatch.setattr("app.main.run_state_store", DummyStore({"last_success_at": "2026-03-03T15:00:00-08:00"}))
    assert _should_backfill_push(now) is False


def test_should_not_backfill_when_already_sent_today(monkeypatch):
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    # last_success_at is today in LA timezone (2026-03-04 08:00 LA)
    monkeypatch.setattr("app.main.run_state_store", DummyStore({"last_success_at": "2026-03-04T08:00:00-08:00"}))
    assert _should_backfill_push(now) is False


def test_should_backfill_when_no_success_record(monkeypatch):
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr("app.main.settings.schedule_time", "07:30")
    monkeypatch.setattr("app.main.run_state_store", DummyStore({}))
    assert _should_backfill_push(now) is True
