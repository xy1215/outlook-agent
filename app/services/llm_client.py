from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from app.models import MailItem, TaskItem


class LLMTaskExtractor:
    def __init__(self, provider: str, api_key: str, model: str, timeout_sec: int = 20) -> None:
        self.provider = (provider or "openai").strip().lower()
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec

    def is_configured(self) -> bool:
        return self.provider == "openai" and bool(self.api_key and self.model)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE)

    @staticmethod
    def _parse_due(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    async def extract_tasks_from_mail(self, mail: MailItem, timezone_name: str) -> list[TaskItem]:
        if not self.is_configured():
            return []

        system = (
            "You extract actionable school tasks from emails. "
            "Return JSON only. Focus on concrete tasks with due dates."
        )
        user = (
            "Extract tasks from this email. Return strictly this JSON schema:\n"
            '{"tasks":[{"title":"string","due_at_iso":"YYYY-MM-DDTHH:MM:SS±HH:MM or null","reason":"string"}]}\n'
            "Rules:\n"
            "1) Keep only actionable tasks (assignments, quizzes, exams, participation).\n"
            "2) Use the provided timezone when interpreting relative times.\n"
            "3) If uncertain about due date, set due_at_iso to null.\n"
            "4) Keep title concise and specific.\n\n"
            f"Timezone: {timezone_name}\n"
            f"Subject: {mail.subject}\n"
            f"Sender: {mail.sender}\n"
            f"Preview: {mail.preview}\n"
            f"Body:\n{mail.body_text[:5000]}"
        )

        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()

        try:
            data = json.loads(self._strip_code_fence(content))
        except Exception:
            return []

        tasks: list[TaskItem] = []
        for row in data.get("tasks", []):
            title = (row.get("title") or "").strip()
            if not title:
                continue
            tasks.append(
                TaskItem(
                    source="llm_mail_extract",
                    title=title,
                    due_at=self._parse_due(row.get("due_at_iso")),
                    course=None,
                    url=mail.url,
                    priority=2,
                )
            )
        return tasks
