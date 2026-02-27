from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
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
    category: Literal["立刻处理", "本周待办", "信息参考"] = "信息参考"
    url: Optional[str] = None


class DailyDigest(BaseModel):
    generated_at: datetime
    date_label: str
    tasks: list[TaskItem]
    important_mails: list[MailItem]
    summary_text: str
    mail_triage: dict[str, list[MailItem]] = Field(default_factory=dict)
    due_push_style: str = ""
    due_push_message: str = ""
