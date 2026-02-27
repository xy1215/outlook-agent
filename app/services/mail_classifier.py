from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
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
        llm_timeout_sec: int = 12,
        llm_max_parallel: int = 6,
    ) -> None:
        self.timezone_name = timezone_name
        self.llm_api_base = llm_api_base.rstrip("/")
        self.llm_api_key = llm_api_key.strip()
        self.llm_model = llm_model.strip()
        self.llm_timeout_sec = max(3, llm_timeout_sec)
        self.llm_max_parallel = max(1, llm_max_parallel)

    def _fallback_bucket(self, mail: MailItem, now: datetime) -> str:
        text = f"{mail.subject} {mail.preview} {mail.body_text[:800]}".lower()
        if any(k in text for k in ["urgent", "asap", "deadline", "exam today", "final reminder"]):
            return "immediate"
        if any(k in text for k in ["this week", "todo", "action required", "assignment"]):
            return "weekly"
        return "reference"

    async def _llm_bucket(self, mail: MailItem, now: datetime) -> str | None:
        if not self.llm_api_key or not self.llm_model:
            return None
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
            async with httpx.AsyncClient(timeout=self.llm_timeout_sec) as client:
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

    async def classify(self, mails: list[MailItem], now: datetime) -> MailBuckets:
        immediate: list[MailItem] = []
        weekly: list[MailItem] = []
        reference: list[MailItem] = []
        labels: dict[int, str] = {}
        sem = asyncio.Semaphore(self.llm_max_parallel)

        async def classify_one(idx: int, mail: MailItem) -> None:
            async with sem:
                label = await self._llm_bucket(mail, now)
            if label is None:
                label = self._fallback_bucket(mail, now)
            labels[idx] = label

        await asyncio.gather(*(classify_one(idx, mail) for idx, mail in enumerate(mails)))

        for idx, mail in enumerate(mails):
            label = labels.get(idx, "reference")
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
