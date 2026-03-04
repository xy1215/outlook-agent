from datetime import datetime, timezone

from app.models import DailyDigest, TaskItem
from app.services.task_state import TaskStateStore, remaining_text, task_id


def _task(title: str, due: datetime) -> TaskItem:
    return TaskItem(source="canvas_feed", title=title, due_at=due, url="https://example.com/task")


def test_task_id_is_stable() -> None:
    due = datetime(2026, 3, 5, 23, 59, tzinfo=timezone.utc)
    t1 = _task("HW1", due)
    t2 = _task("HW1", due)
    assert task_id(t1) == task_id(t2)


def test_remaining_text_formats() -> None:
    now = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)
    due = datetime(2026, 3, 4, 12, 30, tzinfo=timezone.utc)
    assert "剩余" in remaining_text(_task("A", due), now)
    assert "已超时" in remaining_text(_task("A", now.replace(hour=8)), now)


def test_apply_filters_done_and_snoozed(tmp_path) -> None:
    store = TaskStateStore(str(tmp_path / "task_state.json"))
    now = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)
    t1 = _task("Done task", datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc))
    t2 = _task("Snoozed task", datetime(2026, 3, 4, 13, 0, tzinfo=timezone.utc))
    t3 = _task("Active task", datetime(2026, 3, 4, 14, 0, tzinfo=timezone.utc))
    store.mark_done(task_id(t1), now)
    store.snooze_hours(task_id(t2), 2, now)
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-03-04",
        tasks=[t1, t2, t3],
        important_mails=[],
        summary_text="s",
    )
    filtered = store.apply(digest, now)
    assert [x.title for x in filtered.tasks] == ["Active task"]

