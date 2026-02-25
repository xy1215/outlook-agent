from datetime import datetime
from pydantic import BaseModel


class TaskItem(BaseModel):
    source: str
    title: str
    due_at: datetime | None = None
    course: str | None = None
    url: str | None = None
    priority: int = 1


class MailItem(BaseModel):
    source: str = "outlook"
    subject: str
    sender: str
    received_at: datetime
    preview: str = ""
    is_important: bool = False
    url: str | None = None


class DailyDigest(BaseModel):
    generated_at: datetime
    date_label: str
    tasks: list[TaskItem]
    important_mails: list[MailItem]
    summary_text: str
