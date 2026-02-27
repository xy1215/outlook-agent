from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


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


class MailBuckets(BaseModel):
    immediate_action: list[MailItem] = Field(default_factory=list)
    week_todo: list[MailItem] = Field(default_factory=list)
    info_reference: list[MailItem] = Field(default_factory=list)


class DailyDigest(BaseModel):
    generated_at: datetime
    date_label: str
    tasks: list[TaskItem]
    important_mails: list[MailItem]
    mail_buckets: MailBuckets = Field(default_factory=MailBuckets)
    summary_text: str
    push_preview: str = ""
    push_tone: str = ""
    push_urgency: str = "none"
