from app.services.canvas_client import CanvasClient


def test_parse_ics_tasks_extracts_assignment_fields():
    client = CanvasClient("", "", "https://example.com/feed.ics", "America/Los_Angeles")
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Apply for the Bucky Awards
DTSTART:20260301T235900Z
DESCRIPTION:Complete the nomination form https://canvas.wisc.edu/courses/1/assignments/2
URL:https://canvas.wisc.edu/courses/1/assignments/2
CATEGORIES:Leadership
END:VEVENT
END:VCALENDAR
"""
    tasks = client._parse_ics_tasks(ics)
    assert len(tasks) == 1
    assert tasks[0].title == "Apply for the Bucky Awards"
    assert tasks[0].due_at is not None
    assert tasks[0].url == "https://canvas.wisc.edu/courses/1/assignments/2"
    assert tasks[0].course == "Leadership"


def test_parse_ics_tasks_supports_value_date_all_day():
    client = CanvasClient("", "", "https://example.com/feed.ics", "America/Los_Angeles")
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Register for the All-Campus Leadership Conference
DTSTART;VALUE=DATE:20260228
END:VEVENT
END:VCALENDAR
"""
    tasks = client._parse_ics_tasks(ics)
    assert len(tasks) == 1
    assert tasks[0].due_at is not None
    assert tasks[0].due_at.hour == 23
    assert tasks[0].due_at.minute == 59
