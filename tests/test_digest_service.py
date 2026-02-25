from datetime import datetime, timezone

from app.models import MailItem
from app.services.digest_service import DigestService


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
    )


def test_extract_task_and_due_from_canvas_mail_subject_iso():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)

    mail = MailItem(
        subject="Assignment: HW 3 due 2026-03-01 23:59",
        sender="notifications@instructure.com",
        received_at=now,
        preview="Please submit before deadline.",
        is_important=False,
        url="https://example.com/mail/1",
    )

    task = service._task_from_mail(mail, now.astimezone())
    assert task is not None
    assert task.title == "HW 3 due 2026-03-01 23:59"
    assert task.due_at is not None
    assert task.due_at.year == 2026
    assert task.due_at.month == 3
    assert task.due_at.day == 1


def test_extract_task_due_from_us_style_date_in_preview():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)

    mail = MailItem(
        subject="Canvas Submission Reminder",
        sender="canvas@school.edu",
        received_at=now,
        preview="Assignment: Lab report. Due on 3/8 11:59 PM.",
        is_important=False,
        url=None,
    )

    task = service._task_from_mail(mail, now.astimezone())
    assert task is not None
    assert task.title == "Lab report"
    assert task.due_at is not None
    assert task.due_at.month == 3
    assert task.due_at.day == 8


def test_non_canvas_mail_does_not_become_task():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)

    mail = MailItem(
        subject="Weekly campus newsletter",
        sender="news@school.edu",
        received_at=now,
        preview="Events and highlights this week.",
        is_important=False,
        url=None,
    )

    task = service._task_from_mail(mail, now.astimezone())
    assert task is None
