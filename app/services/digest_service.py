from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx

from app.models import DailyDigest, MailItem, TaskItem
from app.services.canvas_client import CanvasClient
from app.services.mail_classifier import MailClassifier
from app.services.outlook_client import OutlookClient


class DigestService:
    def __init__(
        self,
        canvas_client: CanvasClient,
        outlook_client: OutlookClient,
        timezone_name: str,
        lookahead_days: int,
        important_keywords: str,
        task_require_due: bool = True,
        push_due_within_hours: int = 48,
        push_persona: str = "auto",
        mail_classifier: MailClassifier | None = None,
        llm_api_base: str = "https://api.openai.com/v1",
        llm_api_key: str = "",
        llm_model: str = "",
        llm_timeout_sec: int = 12,
        llm_max_parallel: int = 6,
        llm_canvas_max_calls_per_run: int = 24,
        llm_cache_ttl_hours: int = 72,
        llm_canvas_cache_path: str = "data/llm_canvas_cache.json",
    ) -> None:
        self.canvas_client = canvas_client
        self.outlook_client = outlook_client
        self.timezone_name = timezone_name
        self.lookahead_days = lookahead_days
        self.keywords = [k.strip().lower() for k in important_keywords.split(",") if k.strip()]
        self.task_require_due = task_require_due
        self.push_due_within_hours = push_due_within_hours
        self.push_persona = (push_persona or "auto").strip().lower()
        self.mail_classifier = mail_classifier
        self.llm_api_base = llm_api_base.rstrip("/")
        self.llm_api_key = (llm_api_key or "").strip()
        self.llm_model = (llm_model or "").strip()
        self.llm_timeout_sec = max(3, llm_timeout_sec)
        self.llm_max_parallel = max(1, llm_max_parallel)
        self.llm_canvas_max_calls_per_run = max(0, llm_canvas_max_calls_per_run)
        self.llm_cache_ttl_hours = max(1, llm_cache_ttl_hours)
        self.llm_canvas_cache_path = Path(llm_canvas_cache_path)
        self._llm_canvas_cache: dict[str, dict[str, str]] = {}
        self._load_canvas_cache()

    def _load_canvas_cache(self) -> None:
        if not self.llm_canvas_cache_path.exists():
            self._llm_canvas_cache = {}
            return
        try:
            payload = json.loads(self.llm_canvas_cache_path.read_text(encoding="utf-8"))
            self._llm_canvas_cache = payload if isinstance(payload, dict) else {}
        except Exception:
            self._llm_canvas_cache = {}

    def _save_canvas_cache(self) -> None:
        try:
            self.llm_canvas_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.llm_canvas_cache_path.write_text(json.dumps(self._llm_canvas_cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return

    @staticmethod
    def _canvas_cache_key(task: TaskItem) -> str:
        text = f"{task.title}\n{task.course or ''}\n{task.details or ''}\n{task.due_at.isoformat() if task.due_at else ''}".strip().lower()
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _canvas_cache_get(self, key: str, now: datetime) -> bool | None:
        row = self._llm_canvas_cache.get(key)
        if not isinstance(row, dict):
            return None
        label = str(row.get("label", "")).strip().lower()
        ts_raw = row.get("updated_at")
        if label not in {"actionable", "notification"} or not isinstance(ts_raw, str):
            return None
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            return None
        if now - ts > timedelta(hours=self.llm_cache_ttl_hours):
            return None
        return label == "actionable"

    def _canvas_cache_set(self, key: str, actionable: bool, now: datetime) -> None:
        self._llm_canvas_cache[key] = {
            "label": "actionable" if actionable else "notification",
            "updated_at": now.isoformat(),
        }

    def _is_due_soon(self, task: TaskItem, now: datetime) -> bool:
        if task.due_at is None:
            return not self.task_require_due
        local_tz = ZoneInfo(self.timezone_name)
        now_local = now.astimezone(local_tz)
        due_local = task.due_at.astimezone(local_tz)
        today_floor = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        return today_floor <= due_local <= now_local + timedelta(days=self.lookahead_days)

    def _is_mail_important(self, mail: MailItem) -> bool:
        text = f"{mail.subject} {mail.preview} {mail.body_text[:1200]}".lower()
        marketing_onboarding = [
            "welcome to",
            "welcome",
            "onboarding",
            "getting started",
            "product update",
            "newsletter",
            "promo",
            "marketing",
            "offer",
            "sale",
            "figma",
        ]
        high_signal = [
            "action required",
            "required",
            "deadline",
            "due",
            "compliance",
            "disclosure",
            "verify",
            "urgent",
            "asap",
        ]
        # Demote onboarding/marketing style mails unless they carry hard action signals.
        if any(k in text for k in marketing_onboarding) and not any(k in text for k in high_signal):
            return False
        if mail.is_important and any(k in text for k in high_signal):
            return True
        return any(keyword in text for keyword in self.keywords)

    @staticmethod
    def _normalize_task_timeline(task: TaskItem, now: datetime) -> TaskItem:
        if task.published_at is not None:
            return task
        if task.due_at is not None:
            span = timedelta(days=3)
            published_at = task.due_at - span
            if published_at > now:
                published_at = now
            task.published_at = published_at
            return task
        task.published_at = now
        return task

    @staticmethod
    def _fallback_is_actionable_canvas_task(task: TaskItem) -> bool:
        text = f"{task.title} {task.course or ''} {task.details or ''}".lower()
        action_keywords = [
            "assignment",
            "homework",
            "hw",
            "quiz",
            "exam",
            "midterm",
            "final",
            "project",
            "lab",
            "report",
            "submit",
            "submission",
            "participation",
            "discussion",
        ]
        ignore_keywords = [
            "office hour",
            "office hours",
            "announcement",
            "no in-person",
            "lecture",
            "recording",
            "student help",
            "notification",
            "orientation session",
        ]
        if any(k in text for k in ignore_keywords):
            return False
        return any(k in text for k in action_keywords)

    async def _llm_is_actionable_canvas_task(self, task: TaskItem, now: datetime) -> bool | None:
        if not self.llm_api_key or not self.llm_model:
            return None
        payload = {
            "model": self.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify Canvas calendar events into actionable assignment tasks or non-actionable notifications.\n"
                        "Keep only tasks that require student work submission/completion.\n"
                        "Filter out office hours, lectures, announcements, reminder-only events.\n"
                        "Return strict JSON: {\"label\":\"actionable|notification\"}."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "now": now.isoformat(),
                            "title": task.title,
                            "course": task.course,
                            "details": task.details,
                            "due_at": task.due_at.isoformat() if task.due_at else None,
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
            label = str(json.loads(content).get("label", "")).strip().lower()
            if label == "actionable":
                return True
            if label == "notification":
                return False
        except Exception:
            return None
        return None

    async def _filter_canvas_tasks(self, tasks: list[TaskItem], now: datetime) -> list[TaskItem]:
        if not tasks:
            return []
        keep: list[TaskItem] = []
        sem = asyncio.Semaphore(self.llm_max_parallel)
        lock = asyncio.Lock()
        llm_calls = [0]

        async def classify_one(task: TaskItem) -> None:
            cache_key = self._canvas_cache_key(task)
            llm_result = self._canvas_cache_get(cache_key, now)
            if llm_result is None and llm_calls[0] < self.llm_canvas_max_calls_per_run:
                async with sem:
                    model_result = await self._llm_is_actionable_canvas_task(task, now)
                if model_result is not None:
                    llm_calls[0] += 1
                    llm_result = model_result
                    self._canvas_cache_set(cache_key, llm_result, now)
            should_keep = self._fallback_is_actionable_canvas_task(task) if llm_result is None else llm_result
            if not should_keep:
                return
            async with lock:
                keep.append(task)

        await asyncio.gather(*(classify_one(task) for task in tasks))
        self._save_canvas_cache()
        return keep

    async def build(self) -> DailyDigest:
        now = datetime.now(ZoneInfo(self.timezone_name))
        try:
            mails = await self.outlook_client.fetch_recent_messages()
        except Exception:
            mails = []

        canvas_tasks: list[TaskItem] = []
        try:
            canvas_tasks = await self.canvas_client.fetch_todo()
        except Exception:
            # Canvas feed is optional.
            canvas_tasks = []

        tasks = await self._filter_canvas_tasks(canvas_tasks, now)

        due_tasks = [self._normalize_task_timeline(t, now) for t in tasks if self._is_due_soon(t, now)]
        important_mails = [m for m in mails if self._is_mail_important(m)]
        if self.mail_classifier is None:
            mails_immediate: list[MailItem] = []
            mails_weekly: list[MailItem] = []
            mails_reference: list[MailItem] = mails
            mails_internship: list[MailItem] = []
            mails_research: list[MailItem] = []
        else:
            buckets = await self.mail_classifier.classify(mails, now)
            mails_immediate = buckets.immediate
            mails_weekly = buckets.weekly
            mails_reference = buckets.reference
            mails_internship = buckets.internship
            mails_research = buckets.research

        due_tasks.sort(key=lambda x: x.due_at or datetime.max.replace(tzinfo=ZoneInfo(self.timezone_name)))
        important_mails.sort(key=lambda x: x.received_at, reverse=True)
        mails_immediate.sort(key=lambda x: x.received_at, reverse=True)
        mails_weekly.sort(key=lambda x: x.received_at, reverse=True)
        mails_reference.sort(key=lambda x: x.received_at, reverse=True)
        mails_internship.sort(key=lambda x: x.received_at, reverse=True)
        mails_research.sort(key=lambda x: x.received_at, reverse=True)

        summary = (
            f"今天有 {len(due_tasks)} 个 Canvas 待办任务，"
            f"{len(mails_immediate)} 封立刻处理，{len(mails_weekly)} 封本周待办，"
            f"{len(mails_internship)} 封实习机会，{len(mails_research)} 封研究机会。"
        )

        resolved_style = self._resolve_push_style(due_tasks, now)
        push_tasks = self._collect_push_tasks(due_tasks, now)
        digest = DailyDigest(
            generated_at=now,
            date_label=now.strftime("%Y-%m-%d"),
            tasks=due_tasks,
            important_mails=important_mails,
            summary_text=summary,
            mails_immediate=mails_immediate,
            mails_weekly=mails_weekly,
            mails_reference=mails_reference,
            mails_internship=mails_internship,
            mails_research=mails_research,
            due_push_style=resolved_style,
            next_due_hint=self._build_next_due_hint(due_tasks, now),
            due_nudge_current=self._build_persona_nudge(push_tasks, now, resolved_style),
            due_nudge_senior=self._build_persona_nudge(push_tasks, now, "学姐风"),
            due_nudge_cute=self._build_persona_nudge(push_tasks, now, "可爱风"),
        )
        digest.push_preview_senior = self._to_push_text_with_style(digest, "学姐风")
        digest.push_preview_cute = self._to_push_text_with_style(digest, "可爱风")
        digest.push_preview = self.to_push_text(digest)
        return digest

    def _resolve_push_style(self, tasks: list[TaskItem], now: datetime) -> str:
        if self.push_persona == "cute":
            return "可爱风"
        if self.push_persona == "senior":
            return "学姐风"
        due_limit = now + timedelta(hours=self.push_due_within_hours)
        due_floor = now - timedelta(hours=24)
        due_tasks = []
        for task in tasks:
            if task.due_at is None:
                continue
            due_local = task.due_at.astimezone(ZoneInfo(self.timezone_name))
            if due_floor <= due_local <= due_limit:
                due_tasks.append(task)
        if not due_tasks:
            return "可爱风"
        due_tasks.sort(key=lambda x: x.due_at or datetime.max.replace(tzinfo=ZoneInfo(self.timezone_name)))
        top = due_tasks[0]
        if top.due_at is None:
            return "可爱风"
        due_local = top.due_at.astimezone(ZoneInfo(self.timezone_name))
        hours_left = max(0, int((due_local - now).total_seconds() // 3600))
        return "学姐风" if hours_left <= 18 else "可爱风"

    def _build_next_due_hint(self, tasks: list[TaskItem], now: datetime) -> str:
        due_tasks = [task for task in tasks if task.due_at is not None]
        if not due_tasks:
            return "最近 48 小时没有硬截止，按计划推进就好。"
        due_tasks.sort(key=lambda x: x.due_at or datetime.max.replace(tzinfo=ZoneInfo(self.timezone_name)))
        top = due_tasks[0]
        if top.due_at is None:
            return "最近 48 小时没有硬截止，按计划推进就好。"
        due_local = top.due_at.astimezone(ZoneInfo(self.timezone_name))
        hours_left = int((due_local - now).total_seconds() // 3600)
        due_label = due_local.strftime("%m-%d %H:%M")
        if hours_left < 0:
            return f"最近截止：{top.title}（{due_label}）已过期，优先补交并给老师留说明。"
        if hours_left <= 6:
            return f"最近截止：{top.title}（{due_label}），仅剩约 {hours_left} 小时，马上冲刺提交。"
        return f"最近截止：{top.title}（{due_label}），还剩约 {hours_left} 小时，建议今天先完成主干。"

    def _build_persona_nudge(self, push_tasks: list[TaskItem], now: datetime, style: str) -> str:
        if not push_tasks:
            return "今天没有 48 小时内到期任务，节奏很稳，继续保持。"
        top = push_tasks[0]
        if top.due_at is None:
            return ""
        due_local = top.due_at.astimezone(ZoneInfo(self.timezone_name))
        hours_left = max(0, int((due_local - now).total_seconds() // 3600))
        title = top.title

        if hours_left <= 6 and style == "学姐风":
            return f"这是最后的通牒：距离 {title} 截止只剩约 {hours_left} 小时。现在立刻上传并二次核验提交记录（{due_local.strftime('%m-%d %H:%M')} 截止）。"
        if style == "可爱风":
            if hours_left <= 6:
                return f"红色警报啦：{title} 只剩约 {hours_left} 小时，先把可提交版本上传，提交后记得回看一次（{due_local.strftime('%m-%d %H:%M')} 截止）。"
            return (
                f"小提醒来啦：{title} 还剩约 {hours_left} 小时，"
                f"目标先定成 25 分钟冲一段，今天的你会感谢现在的自己。截止参考 {due_local.strftime('%m-%d %H:%M')}。"
            )
        return (
            f"学姐催一下：{title} 距离截止约 {hours_left} 小时。"
            f"现在就开工 25 分钟，先交可提交版本，别把主动权让给ddl（{due_local.strftime('%m-%d %H:%M')} 截止）。"
        )

    def _collect_push_tasks(self, tasks: list[TaskItem], now: datetime) -> list[TaskItem]:
        due_limit = now + timedelta(hours=self.push_due_within_hours)
        due_floor = now - timedelta(hours=24)
        push_tasks: list[TaskItem] = []
        for task in tasks:
            if task.due_at is None:
                continue
            due_local = task.due_at.astimezone(ZoneInfo(self.timezone_name))
            if due_floor <= due_local <= due_limit:
                push_tasks.append(task)
        push_tasks.sort(key=lambda x: x.due_at or datetime.max.replace(tzinfo=ZoneInfo(self.timezone_name)))
        return push_tasks

    def _to_push_text_with_style(self, digest: DailyDigest, style: str) -> str:
        now = digest.generated_at
        push_tasks = self._collect_push_tasks(digest.tasks, now)
        lines = [digest.summary_text, f"[催办风格] {style}", self._build_persona_nudge(push_tasks, now, style)]
        for task in push_tasks[:5]:
            due = task.due_at.strftime("%m-%d %H:%M") if task.due_at else "无截止时间"
            lines.append(f"[任务] {task.title} | {due}")
        for mail in digest.mails_immediate[:3]:
            lines.append(f"[立刻处理] {mail.subject} | {mail.sender}")
        for mail in digest.mails_weekly[:2]:
            lines.append(f"[本周待办] {mail.subject} | {mail.sender}")
        for mail in digest.important_mails[:2]:
            lines.append(f"[邮件] {mail.subject} | {mail.sender}")
        return "\n".join(lines)

    def to_push_text(self, digest: DailyDigest) -> str:
        style = digest.due_push_style or self._resolve_push_style(digest.tasks, digest.generated_at)
        return self._to_push_text_with_style(digest, style)
