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
        task_mode="action_only",
        task_action_keywords="due,deadline,exam,quiz,submission,homework,hw,project,midterm,final,participation,lab",
        task_noise_keywords="assignment graded,graded:,office hours moved,daily digest,announcement posted",
        task_require_due=True,
        push_due_within_hours=48,
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


def test_extract_task_due_from_today_time_phrase():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    mail = MailItem(
        subject="Make-up exam today at 5:45 PM",
        sender="notifications@instructure.com",
        received_at=now,
        preview="Exam will be held today at 5:45 PM in room B239.",
        is_important=False,
        url=None,
    )
    task = service._task_from_mail(mail, now.astimezone())
    assert task is not None
    assert task.due_at is not None


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


def test_assignment_graded_is_filtered_as_noise():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    mail = MailItem(
        subject="Assignment Graded: Quiz 2",
        sender="notifications@instructure.com",
        received_at=now,
        preview="Your assignment has been graded.",
        is_important=False,
        url=None,
    )
    assert service._task_from_mail(mail, now.astimezone()) is None


def test_push_text_only_includes_due_tasks_within_window():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-02-25",
        tasks=[
            TaskItem(source="outlook_canvas_mail", title="Near due", due_at=datetime(2026, 2, 26, 0, 0, tzinfo=timezone.utc)),
            TaskItem(source="outlook_canvas_mail", title="Far due", due_at=datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc)),
            TaskItem(source="outlook_canvas_mail", title="No due", due_at=None),
        ],
        important_mails=[],
        summary_text="s",
    )
    text = service.to_push_text(digest)
    assert "Near due" in text
    assert "Far due" not in text
    assert "No due" not in text


def test_requires_due_filters_mail_without_deadline():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    mail = MailItem(
        subject="Quiz discussion this week",
        sender="notifications@instructure.com",
        received_at=now,
        preview="Please prepare for upcoming discussion.",
        is_important=False,
        url=None,
    )
    assert service._task_from_mail(mail, now.astimezone()) is None


def test_extracts_multiple_tasks_from_body_due_blocks():
    service = make_service()
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    mail = MailItem(
        subject="This Week's Deadlines: Chapter 5",
        sender="notifications@instructure.com",
        received_at=now,
        preview="Please review weekly deadlines.",
        body_text=(
            "DUE TONIGHT, Monday, February 23 at 11:59 PM Central Time\n"
            "Participation for Guest Speaker: Joe Barhoumeh, CPT\n"
            "DUE Thursday, February 26 at 11:59 PM Central Time\n"
            "Lipids Assignment\n"
            "Chapter 5 Quiz\n"
        ),
        is_important=False,
        url=None,
    )

    tasks = service._tasks_from_mail(mail, now.astimezone())
    assert len(tasks) >= 2
    titles = [t.title for t in tasks]
    assert any("Participation for Guest Speaker" in t for t in titles)
    assert any("Chapter 5 Quiz" in t for t in titles)


def test_mail_classifier_fallback_buckets():
    classifier = MailClassifier(
        timezone_name="America/Los_Angeles",
        llm_api_key="",
        llm_model="",
    )
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    mails = [
        MailItem(
            subject="Final reminder: project due soon",
            sender="noreply@school.edu",
            received_at=now,
            preview="Submit ASAP.",
        ),
        MailItem(
            subject="Assignment planning this week",
            sender="canvas@school.edu",
            received_at=now,
            preview="Please finish this week.",
        ),
        MailItem(
            subject="Campus event highlights",
            sender="news@school.edu",
            received_at=now,
            preview="FYI",
        ),
    ]
    due_map = {
        0: datetime(2026, 2, 26, 9, 0, tzinfo=timezone.utc),
        1: datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc),
        2: None,
    }
    buckets = asyncio.run(classifier.classify(mails, due_map, now))
    assert len(buckets.immediate) == 1
    assert len(buckets.weekly) == 1
    assert len(buckets.reference) == 1


def test_push_text_contains_persona_nudge():
    service = DigestService(
        canvas_client=DummyCanvasClient(),
        outlook_client=DummyOutlookClient(),
        timezone_name="America/Los_Angeles",
        lookahead_days=7,
        important_keywords="urgent,important,deadline,exam,quiz,project",
        push_persona="senior",
    )
    now = datetime(2026, 2, 25, 9, 0, tzinfo=timezone.utc)
    digest = DailyDigest(
        generated_at=now,
        date_label="2026-02-25",
        tasks=[
            TaskItem(source="outlook_canvas_mail", title="Midterm prep", due_at=datetime(2026, 2, 26, 0, 0, tzinfo=timezone.utc)),
        ],
        important_mails=[],
        summary_text="s",
        mails_immediate=[],
        mails_weekly=[],
        mails_reference=[],
    )
    text = service.to_push_text(digest)
    assert "学姐催一下" in text
