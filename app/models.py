from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


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
    category: str = ""


class DailyDigest(BaseModel):
    generated_at: datetime
    date_label: str
    tasks: list[TaskItem]
    important_mails: list[MailItem]
    summary_text: str
    mails_immediate: list[MailItem] = Field(default_factory=list)
    mails_weekly: list[MailItem] = Field(default_factory=list)
    mails_reference: list[MailItem] = Field(default_factory=list)
    push_preview: str = ""
    due_push_style: str = ""
    push_preview_senior: str = ""
    push_preview_cute: str = ""
