from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import httpx

from app.models import MailItem


@dataclass
class MailBuckets:
    immediate: list[MailItem]
    weekly: list[MailItem]
    reference: list[MailItem]
    internship: list[MailItem]
    research: list[MailItem]


class MailClassifier:
    def __init__(
        self,
        timezone_name: str,
        llm_api_base: str = "https://api.openai.com/v1",
        llm_api_key: str = "",
        llm_model: str = "",
        llm_timeout_sec: int = 12,
        llm_max_parallel: int = 6,
        llm_enabled: bool = False,
        llm_max_calls_per_run: int = 8,
        llm_fail_fast_threshold: int = 3,
        llm_cache_ttl_hours: int = 72,
        llm_cache_path: str = "data/llm_mail_cache.json",
    ) -> None:
        self.timezone_name = timezone_name
        self.llm_api_base = llm_api_base.rstrip("/")
        self.llm_api_key = llm_api_key.strip()
        self.llm_model = llm_model.strip()
        self.llm_timeout_sec = max(3, llm_timeout_sec)
        self.llm_max_parallel = max(1, llm_max_parallel)
        self.llm_enabled = llm_enabled
        self.llm_max_calls_per_run = max(0, llm_max_calls_per_run)
        self.llm_fail_fast_threshold = max(1, llm_fail_fast_threshold)
        self.llm_cache_ttl_hours = max(1, llm_cache_ttl_hours)
        self.llm_cache_path = Path(llm_cache_path)
        self._llm_cache: dict[str, dict[str, str]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.llm_cache_path.exists():
            self._llm_cache = {}
            return
        try:
            payload = json.loads(self.llm_cache_path.read_text(encoding="utf-8"))
            self._llm_cache = payload if isinstance(payload, dict) else {}
        except Exception:
            self._llm_cache = {}

    def _save_cache(self) -> None:
        try:
            self.llm_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.llm_cache_path.write_text(json.dumps(self._llm_cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return

    @staticmethod
    def _cache_key(mail: MailItem) -> str:
        text = f"{mail.subject}\n{mail.sender}\n{mail.preview}\n{mail.body_text[:1200]}".strip().lower()
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str, now: datetime) -> str | None:
        row = self._llm_cache.get(key)
        if not isinstance(row, dict):
            return None
        label = str(row.get("label", "")).strip().lower()
        ts_raw = row.get("updated_at")
        if label not in {"immediate", "weekly", "reference", "internship", "research"}:
            return None
        if not isinstance(ts_raw, str):
            return None
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            return None
        if now - ts > timedelta(hours=self.llm_cache_ttl_hours):
            return None
        return label

    def _cache_set(self, key: str, label: str, now: datetime) -> None:
        self._llm_cache[key] = {"label": label, "updated_at": now.isoformat()}

    def _fallback_bucket(self, mail: MailItem, now: datetime) -> str:
        text = f"{mail.subject} {mail.preview} {mail.body_text[:800]}".lower()
        graded_noise = [
            "assignment graded",
            "graded:",
            "your assignment has been graded",
            "submission posted",
        ]
        internship_signal = [
            "internship",
            "summer analyst",
            "new grad",
            "campus recruiting",
            "career fair",
            "referral",
            "co-op",
            "intern role",
        ]
        research_signal = [
            "research opportunity",
            "research study",
            "participant",
            "lab position",
            "phd student",
            "survey study",
            "irb",
            "ra position",
            "research assistant",
        ]
        if any(k in text for k in graded_noise):
            return "reference"
        if any(k in text for k in internship_signal):
            return "internship"
        if any(k in text for k in research_signal):
            return "research"
        if any(k in text for k in ["urgent", "asap", "deadline", "exam today", "final reminder"]):
            return "immediate"
        if any(k in text for k in ["this week", "todo", "action required", "assignment"]):
            return "weekly"
        return "reference"

    async def _llm_bucket(self, mail: MailItem, now: datetime) -> str | None:
        if not self.llm_enabled or not self.llm_api_key or not self.llm_model:
            return None
        prompt = (
            "You classify student emails into one of exactly five labels: "
            "immediate, weekly, reference, internship, research.\n"
            "Rules:\n"
            "- immediate: urgent action needed now or within 48h.\n"
            "- weekly: action needed this week but not immediate.\n"
            "- reference: informational only.\n"
            "- internship: internship/co-op/new-grad recruiting opportunities.\n"
            "- research: research study, participant recruitment, RA/lab opportunities.\n"
            "- Strong noise: any 'assignment graded' or grade-posted notification should be reference.\n"
            "Return strict JSON: {\"label\":\"immediate|weekly|reference|internship|research\"}."
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
            if label in {"immediate", "weekly", "reference", "internship", "research"}:
                return label
        except Exception:
            return None
        return None

    async def classify(self, mails: list[MailItem], now: datetime) -> MailBuckets:
        immediate: list[MailItem] = []
        weekly: list[MailItem] = []
        reference: list[MailItem] = []
        internship: list[MailItem] = []
        research: list[MailItem] = []
        labels: dict[int, str] = {}
        sem = asyncio.Semaphore(self.llm_max_parallel)
        budget_lock = asyncio.Lock()
        llm_state = {"remaining": self.llm_max_calls_per_run, "failures": 0, "circuit_open": False}

        async def classify_one(idx: int, mail: MailItem) -> None:
            cache_key = self._cache_key(mail)
            label = self._cache_get(cache_key, now)
            should_try_llm = False
            if label is None:
                async with budget_lock:
                    if (not llm_state["circuit_open"]) and llm_state["remaining"] > 0:
                        llm_state["remaining"] -= 1  # Attempt consumes budget regardless of success/failure.
                        should_try_llm = True
            if label is None and should_try_llm:
                async with sem:
                    llm_label = await self._llm_bucket(mail, now)
                if llm_label is not None:
                    label = llm_label
                    self._cache_set(cache_key, label, now)
                    async with budget_lock:
                        llm_state["failures"] = 0
                else:
                    async with budget_lock:
                        llm_state["failures"] += 1
                        if llm_state["failures"] >= self.llm_fail_fast_threshold:
                            llm_state["circuit_open"] = True
            if label is None:
                label = self._fallback_bucket(mail, now)
            labels[idx] = label

        await asyncio.gather(*(classify_one(idx, mail) for idx, mail in enumerate(mails)))
        self._save_cache()

        for idx, mail in enumerate(mails):
            label = labels.get(idx, "reference")
            if label == "immediate":
                mail.category = "立刻处理"
                immediate.append(mail)
            elif label == "weekly":
                mail.category = "本周待办"
                weekly.append(mail)
            elif label == "internship":
                mail.category = "实习机会"
                internship.append(mail)
            elif label == "research":
                mail.category = "研究机会"
                research.append(mail)
            else:
                mail.category = "信息参考"
                reference.append(mail)

        return MailBuckets(
            immediate=immediate,
            weekly=weekly,
            reference=reference,
            internship=internship,
            research=research,
        )
