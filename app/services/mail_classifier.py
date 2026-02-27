from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json

import httpx

from app.models import MailItem


@dataclass
class MailBuckets:
    immediate: list[MailItem]
    weekly: list[MailItem]
    reference: list[MailItem]


class MailClassifier:
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

    def _fallback_bucket(self, mail: MailItem, due_at: datetime | None, now: datetime) -> str:
        text = f"{mail.subject} {mail.preview} {mail.body_text[:800]}".lower()
        if due_at and due_at <= now + timedelta(hours=48):
            return "immediate"
        if due_at and due_at <= now + timedelta(days=7):
            return "weekly"
        if any(k in text for k in ["urgent", "asap", "deadline", "exam today", "final reminder"]):
            return "immediate"
        if any(k in text for k in ["this week", "todo", "action required", "assignment"]):
            return "weekly"
        return "reference"

    async def _llm_bucket(self, mail: MailItem, due_at: datetime | None, now: datetime) -> str | None:
        if not self.llm_api_key or not self.llm_model:
            return None

        due_text = due_at.isoformat() if due_at else "none"
        prompt = (
            "You classify student emails into one of exactly three labels: "
            "immediate, weekly, reference.\n"
            "Rules:\n"
            "- immediate: urgent action needed now or within 48h.\n"
            "- weekly: action needed this week but not immediate.\n"
            "- reference: informational only.\n"
            "Return strict JSON: {\"label\":\"immediate|weekly|reference\"}."
        )
        user = {
            "now": now.isoformat(),
            "subject": mail.subject,
            "preview": mail.preview,
            "body_text": mail.body_text[:1200],
            "sender": mail.sender,
            "due_at": due_text,
        }
        payload = {
            "model": self.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(user, ensure_ascii=True)},
            ],
        }
        headers = {"Authorization": f"Bearer {self.llm_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.post(f"{self.llm_api_base}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            label = str(parsed.get("label", "")).strip().lower()
            if label in {"immediate", "weekly", "reference"}:
                return label
        except Exception:
            return None
        return None

    async def classify(self, mails: list[MailItem], due_map: dict[int, datetime | None], now: datetime) -> MailBuckets:
        immediate: list[MailItem] = []
        weekly: list[MailItem] = []
        reference: list[MailItem] = []

        for idx, mail in enumerate(mails):
            due_at = due_map.get(idx)
            label = await self._llm_bucket(mail, due_at, now)
            if label is None:
                label = self._fallback_bucket(mail, due_at, now)

            if label == "immediate":
                mail.category = "立刻处理"
                immediate.append(mail)
            elif label == "weekly":
                mail.category = "本周待办"
                weekly.append(mail)
            else:
                mail.category = "信息参考"
                reference.append(mail)

        return MailBuckets(immediate=immediate, weekly=weekly, reference=reference)
