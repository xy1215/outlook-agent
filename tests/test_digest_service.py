from datetime import datetime, timezone
import asyncio

from app.models import DailyDigest, MailItem, TaskItem
from app.services.digest_service import DigestService
from app.services.mail_classifier import MailClassifier


class DummyCanvasClient:
    async def fetch_todo(self):
        return []


class DummyOutlookClient:
    async def fetch_recent_messages(self, max_count: int = 20):
        return []


def make_service() -> DigestService:
    return DigestService(
        canvas_client=DummyCanvasClient(),
        outlook_client=DummyOutlookClient(),
        timezone_name="America/Los_Angeles",
        lookahead_days=7,
        important_keywords="urgent,important,deadline,exam,quiz,project",
        task_require_due=True,
        push_due_within_hours=48,
    )


def test_push_text_only_includes_due_tasks_within_window():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-02-25",
        tasks=[
            TaskItem(source="canvas_feed", title="Near due", due_at=datetime(2026, 2, 26, 0, 0, tzinfo=timezone.utc)),
            TaskItem(source="canvas_feed", title="Far due", due_at=datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc)),
            TaskItem(source="canvas_feed", title="No due", due_at=None),
        ],
        important_mails=[],
        summary_text="s",
    )
    text = service.to_push_text(digest)
    assert "Near due" in text
    assert "Far due" not in text
    assert "No due" not in text


def test_is_due_soon_excludes_tasks_before_today_floor():
    service = make_service()
    now = datetime(2026, 2, 28, 2, 0, tzinfo=timezone.utc)  # 2026-02-27 18:00 PST
    yesterday_due = TaskItem(source="canvas_feed", title="Old task", due_at=datetime(2026, 2, 27, 7, 59, tzinfo=timezone.utc))
    today_due = TaskItem(source="canvas_feed", title="Today task", due_at=datetime(2026, 2, 27, 10, 0, tzinfo=timezone.utc))
    assert not service._is_due_soon(yesterday_due, now)
    assert service._is_due_soon(today_due, now)


def test_filter_canvas_tasks_keeps_assignments_and_drops_notifications():
    service = make_service()
    now = datetime(2026, 2, 28, 2, 0, tzinfo=timezone.utc)
    tasks = [
        TaskItem(source="canvas_feed", title="HW5", details="Submit before deadline", due_at=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)),
        TaskItem(source="canvas_feed", title="Office Hours", details="Professor office hours session", due_at=datetime(2026, 3, 1, 1, 0, tzinfo=timezone.utc)),
    ]
    kept = asyncio.run(service._filter_canvas_tasks(tasks, now))
    assert len(kept) == 1
    assert kept[0].title == "HW5"


def test_mail_classifier_fallback_buckets_without_due_map():
    classifier = MailClassifier(timezone_name="America/Los_Angeles", llm_api_key="", llm_model="")
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    mails = [
        MailItem(subject="Final reminder: project due soon", sender="noreply@school.edu", received_at=now, preview="Submit ASAP."),
        MailItem(subject="Assignment planning this week", sender="canvas@school.edu", received_at=now, preview="Please finish this week."),
        MailItem(subject="Campus event highlights", sender="news@school.edu", received_at=now, preview="FYI"),
    ]
    buckets = asyncio.run(classifier.classify(mails, now))
    assert len(buckets.immediate) == 1
    assert len(buckets.weekly) == 1
    assert len(buckets.reference) == 1
    assert buckets.immediate[0].category == "立刻处理"
    assert buckets.weekly[0].category == "本周待办"
    assert buckets.reference[0].category == "信息参考"


def test_resolve_push_style_for_auto_persona():
    service = DigestService(
        canvas_client=DummyCanvasClient(),
        outlook_client=DummyOutlookClient(),
        timezone_name="America/Los_Angeles",
        lookahead_days=7,
        important_keywords="urgent,important,deadline,exam,quiz,project",
        push_persona="auto",
    )
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-02-25",
        tasks=[TaskItem(source="canvas_feed", title="Soon due", due_at=datetime(2026, 2, 25, 16, 0, tzinfo=timezone.utc))],
        important_mails=[],
        summary_text="s",
        mails_immediate=[],
        mails_weekly=[],
        mails_reference=[],
    )
    digest.due_push_style = service._resolve_push_style(digest.tasks, now)
    assert digest.due_push_style == "学姐风"
