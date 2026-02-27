from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import re

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
        llm_timeout_sec: int = 12,
        llm_max_parallel: int = 6,
        trusted_sender_domains: str = ".edu,instructure.com,canvaslms.com",
        blocked_sender_keywords: str = "apartment,lease,housing,realtor,zillow,marketing,promo,discount,coupon,ad",
    ) -> None:
        self.timezone_name = timezone_name
        self.llm_api_base = llm_api_base.rstrip("/")
        self.llm_api_key = llm_api_key.strip()
        self.llm_model = llm_model.strip()
        self.llm_timeout_sec = max(3, llm_timeout_sec)
        self.llm_max_parallel = max(1, llm_max_parallel)
        self.trusted_sender_domains = [x.strip().lower() for x in trusted_sender_domains.split(",") if x.strip()]
        self.blocked_sender_keywords = [x.strip().lower() for x in blocked_sender_keywords.split(",") if x.strip()]

    @staticmethod
    def _extract_sender_email(sender: str) -> str:
        text = (sender or "").strip().lower()
        if not text:
            return ""
        match = re.search(r"<([^>]+)>", text)
        if match:
            return match.group(1).strip()
        if "@" in text and " " not in text:
            return text
        inline = re.search(r"([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})", text)
        return inline.group(1) if inline else text

    def _is_trusted_sender(self, sender: str) -> bool:
        sender_l = (sender or "").strip().lower()
        if not sender_l:
            return False
        if any(keyword in sender_l for keyword in self.blocked_sender_keywords):
            return False
        email = self._extract_sender_email(sender_l)
        domain = email.split("@", 1)[1] if "@" in email else ""
        for marker in self.trusted_sender_domains:
            if marker.startswith("."):
                if domain.endswith(marker):
                    return True
            elif domain == marker or domain.endswith(f".{marker}"):
                return True
        return False

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
            async with httpx.AsyncClient(timeout=self.llm_timeout_sec) as client:
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
        if not self.llm_api_key or not self.llm_model:
            return MailActionScan(tasks=[], due_map={idx: None for idx, _ in enumerate(mails)})

        tasks: list[TaskItem] = []
        due_map: dict[int, datetime | None] = {}
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(self.llm_max_parallel)

        async def scan_one(idx: int, mail: MailItem) -> None:
            if not self._is_trusted_sender(mail.sender):
                async with lock:
                    due_map[idx] = None
                return
            async with sem:
                extracted, best_due = await self._llm_extract_one(mail, now)
            async with lock:
                due_map[idx] = best_due
                tasks.extend(extracted)

        await asyncio.gather(*(scan_one(idx, mail) for idx, mail in enumerate(mails)))

        return MailActionScan(tasks=tasks, due_map=due_map)
