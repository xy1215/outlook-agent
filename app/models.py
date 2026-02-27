from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class TaskItem(BaseModel):
    source: str
    title: str
    due_at: Optional[datetime] = None
    course: Optional[str] = None
    url: Optional[str] = None
    priority: int = 1


class MailItem(BaseModel):
    source: str = "outlook"
    subject: str
    sender: str
    received_at: datetime
    preview: str = ""
    body_text: str = ""
    is_important: bool = False
    url: Optional[str] = None


class DailyDigest(BaseModel):
    generated_at: datetime
    date_label: str
    tasks: list[TaskItem]
    important_mails: list[MailItem]
    summary_text: str
    mail_triage: dict[str, list[MailItem]] = {}
    due_push_message: str = ""
