from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import httpx

from app.models import MailItem, TaskItem


@dataclass
class MailActionScan:
    tasks: list[TaskItem]
    due_map: dict[int, datetime | None]


class MailActionExtractor:
    def __init__(
        self,
        timezone_name: str,
        llm_api_base: str = "https://api.openai.com/v1",
        llm_api_key: str = "",
        llm_model: str = "",
    ) -> None:
        self.timezone_name = timezone_name
        self.llm_api_base = llm_api_base.rstrip("/")
        self.llm_api_key = llm_api_key.strip()
        self.llm_model = llm_model.strip()

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _llm_extract_one(self, mail: MailItem, now: datetime) -> tuple[list[TaskItem], datetime | None]:
        if not self.llm_api_key or not self.llm_model:
            return [], None

        schema_hint = (
            "Return strict JSON with this shape only: "
            "{\"mail_type\":\"notification|action\",\"tasks\":[{\"title\":\"...\",\"action_type\":\"submit|register|verify|other\","
            "\"due_at\":\"ISO8601 or null\",\"published_at\":\"ISO8601 or null\",\"course\":\"string or null\",\"reason\":\"short\"}]}"
        )
        prompt = (
            "You are an academic inbox triage engine. Read the full email and decide if it is notification-only or actionable.\n"
            "Actionable means the student must perform concrete operations such as submit, register, or verify.\n"
            "If the mail is only an announcement, newsletter, reminder with no required operation, classify it as notification and return empty tasks.\n"
            "For action tasks, keep only tasks requiring submit/register/verify/other concrete action.\n"
            "Use full email body, not subject-only.\n"
            + schema_hint
        )

        payload = {
            "model": self.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "now": now.isoformat(),
                            "subject": mail.subject,
                            "sender": mail.sender,
                            "received_at": mail.received_at.isoformat(),
                            "preview": mail.preview,
                            "body_text": mail.body_text,
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
        }

        headers = {"Authorization": f"Bearer {self.llm_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{self.llm_api_base}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except Exception:
            return [], None

        tasks: list[TaskItem] = []
        best_due: datetime | None = None

        for row in parsed.get("tasks", []):
            action_type = str(row.get("action_type", "")).strip().lower()
            if action_type not in {"submit", "register", "verify", "other"}:
                continue
            title = str(row.get("title", "")).strip()
            if not title:
                continue

            due_at = self._parse_dt(row.get("due_at"))
            published_at = self._parse_dt(row.get("published_at")) or mail.received_at
            if due_at is not None and best_due is None:
                best_due = due_at
            if due_at is not None and best_due is not None and due_at < best_due:
                best_due = due_at

            course = row.get("course")
            tasks.append(
                TaskItem(
                    source="outlook_llm_action",
                    title=title,
                    due_at=due_at,
                    published_at=published_at,
                    course=course if isinstance(course, str) and course.strip() else None,
                    url=mail.url,
                    priority=2 if due_at else 1,
                )
            )

        return tasks, best_due

    async def extract(self, mails: list[MailItem], now: datetime) -> MailActionScan:
        tasks: list[TaskItem] = []
        due_map: dict[int, datetime | None] = {}

        for idx, mail in enumerate(mails):
            extracted, best_due = await self._llm_extract_one(mail, now)
            due_map[idx] = best_due
            tasks.extend(extracted)

        return MailActionScan(tasks=tasks, due_map=due_map)
