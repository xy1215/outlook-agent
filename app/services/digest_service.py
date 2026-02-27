from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import re
from zoneinfo import ZoneInfo

import httpx

REL_DUE_RE = re.compile(r"\b(today|tomorrow)\b(?:\s+(?:at\s+)?)?(\d{1,2}:\d{2})?\s*(am|pm|AM|PM)?")
ISO_DUE_RE = re.compile(r"(20\d{2}-\d{1,2}-\d{1,2})(?:\s+(\d{1,2}:\d{2}))?")
US_DUE_RE = re.compile(r"(\d{1,2}/\d{1,2})(?:/(\d{2,4}))?(?:\s+(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?)?")
MONTH_DUE_RE = re.compile(
    r"\b("
    r"Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|"
    r"Oct|October|Nov|November|Dec|December"
    r")\s+(\d{1,2})(?:,\s*(20\d{2}))?(?:\s+(?:at\s+)?(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?)?"
)

from app.models import DailyDigest, MailBuckets, MailItem, TaskItem
from app.services.canvas_client import CanvasClient
from app.services.llm_client import LLMTaskExtractor
from app.services.outlook_client import OutlookClient


class DigestService:
    def __init__(
        self,
        canvas_client: CanvasClient,
        outlook_client: OutlookClient,
        timezone_name: str,
        lookahead_days: int,
        important_keywords: str,
        task_mode: str = "action_only",
        task_action_keywords: str = "due,deadline,exam,quiz,submission,assignment,homework,hw,project,midterm,final,participation,lab",
        task_noise_keywords: str = "assignment graded,graded:,office hours moved,daily digest,announcement posted",
        task_require_due: bool = True,
        push_due_within_hours: int = 48,
        push_tone: str = "学姐风",
        llm_enabled: bool = False,
        llm_max_mails: int = 8,
        llm_client: LLMTaskExtractor | None = None,
        llm_api_key: str = "",
        llm_base_url: str = "https://api.openai.com/v1",
        llm_model: str = "gpt-4o-mini",
    ) -> None:
        self.canvas_client = canvas_client
        self.outlook_client = outlook_client
        self.timezone_name = timezone_name
        self.local_tz = ZoneInfo(self.timezone_name)
        self.lookahead_days = lookahead_days
        self.keywords = [k.strip().lower() for k in important_keywords.split(",") if k.strip()]
        self.task_mode = (task_mode or "action_only").strip().lower()
        self.action_keywords = [k.strip().lower() for k in task_action_keywords.split(",") if k.strip()]
        self.noise_keywords = [k.strip().lower() for k in task_noise_keywords.split(",") if k.strip()]
        self.task_require_due = task_require_due
        self.push_due_within_hours = push_due_within_hours
        self.push_tone = (push_tone or "学姐风").strip()
        self.llm_enabled = llm_enabled
        self.llm_max_mails = llm_max_mails
        self.llm_client = llm_client
        self.llm_api_key = llm_api_key
        self.llm_base_url = (llm_base_url or "https://api.openai.com/v1").rstrip("/")
        self.llm_model = llm_model or "gpt-4o-mini"

    def _is_due_soon(self, task: TaskItem, now: datetime) -> bool:
        if task.due_at is None:
            return not self.task_require_due
        due_local = task.due_at.astimezone(self.local_tz)
        return due_local <= now + timedelta(days=self.lookahead_days)

    def _is_mail_important(self, mail: MailItem) -> bool:
        if mail.is_important:
            return True
        text = f"{mail.subject} {mail.preview} {mail.body_text[:1200]}".lower()
        return any(keyword in text for keyword in self.keywords)

    def _is_noise_mail(self, mail: MailItem) -> bool:
        # Noise filtering must be conservative: only look at subject.
        text = mail.subject.lower()
        return any(keyword in text for keyword in self.noise_keywords)

    def _is_actionable(self, mail: MailItem, due_at: datetime | None) -> bool:
        if due_at is not None:
            return True
        text = f"{mail.subject} {mail.preview} {mail.body_text[:1200]}".lower()
        return any(keyword in text for keyword in self.action_keywords)

    @staticmethod
    def _clean_task_title(raw: str) -> str:
        text = re.sub(r"\s+", " ", raw).strip(" -:|")
        return text or "Canvas task"

    @staticmethod
    def _normalize_title_for_key(title: str) -> str:
        t = title.lower()
        t = re.sub(r"access code.*$", " ", t)
        t = re.sub(r"\([^)]*\)", " ", t)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def _is_generic_task_title(title: str) -> bool:
        t = title.lower().strip()
        generic_phrases = [
            "recent canvas notifications",
            "this week's deadlines",
            "weekly deadlines",
            "canvas announcement",
            "course announcement",
            "check out upcoming deadlines",
        ]
        return any(p in t for p in generic_phrases)

    def _parse_deadline_from_text(self, text: str, now: datetime) -> datetime | None:
        local_tz = self.local_tz
        text_l = text.lower()

        rel_match = REL_DUE_RE.search(text)
        if rel_match:
            day_word = rel_match.group(1).lower()
            time_part = rel_match.group(2)
            ampm = rel_match.group(3)
            base = now.astimezone(local_tz)
            if day_word == "tomorrow":
                base = base + timedelta(days=1)
            hour, minute = 23, 59
            if time_part:
                t = datetime.strptime(time_part, "%H:%M")
                hour, minute = t.hour, t.minute
                if ampm:
                    ampm_l = ampm.lower()
                    if ampm_l == "pm" and hour != 12:
                        hour += 12
                    if ampm_l == "am" and hour == 12:
                        hour = 0
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # ISO-like: 2026-03-08 23:59 or 2026-03-08
        iso_match = ISO_DUE_RE.search(text)
        if iso_match:
            date_part = iso_match.group(1)
            time_part = iso_match.group(2) or "23:59"
            try:
                return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M").replace(tzinfo=local_tz)
            except ValueError:
                pass

        # US-like: 3/8 11:59 PM, 03/08/2026, 3/8
        us_match = US_DUE_RE.search(text)
        if us_match:
            mmdd = us_match.group(1)
            year_part = us_match.group(2)
            time_part = us_match.group(3)
            ampm = us_match.group(4)
            year = int(year_part) if year_part else now.year
            if year < 100:
                year += 2000
            hour = 23
            minute = 59
            if time_part:
                t = datetime.strptime(time_part, "%H:%M")
                hour, minute = t.hour, t.minute
                if ampm:
                    ampm_l = ampm.lower()
                    if ampm_l == "pm" and hour != 12:
                        hour += 12
                    if ampm_l == "am" and hour == 12:
                        hour = 0
            try:
                parsed = datetime.strptime(f"{year}/{mmdd} {hour:02d}:{minute:02d}", "%Y/%m/%d %H:%M").replace(tzinfo=local_tz)
                if not year_part and parsed < now - timedelta(days=180):
                    parsed = parsed.replace(year=year + 1)
                return parsed
            except ValueError:
                pass

        # Month words: Mar 8, March 8 11:59 PM
        month_match = MONTH_DUE_RE.search(text)
        if month_match:
            month_word = month_match.group(1)
            day = int(month_match.group(2))
            year = int(month_match.group(3)) if month_match.group(3) else now.year
            time_part = month_match.group(4)
            ampm = month_match.group(5)
            month_number = datetime.strptime(month_word[:3], "%b").month
            hour, minute = 23, 59
            if time_part:
                t = datetime.strptime(time_part, "%H:%M")
                hour, minute = t.hour, t.minute
                if ampm:
                    ampm_l = ampm.lower()
                    if ampm_l == "pm" and hour != 12:
                        hour += 12
                    if ampm_l == "am" and hour == 12:
                        hour = 0
            try:
                parsed = datetime(year, month_number, day, hour, minute, tzinfo=local_tz)
                if not month_match.group(3) and parsed < now - timedelta(days=180):
                    parsed = parsed.replace(year=year + 1)
                return parsed
            except ValueError:
                return None

        if "midnight" in text_l:
            return now.astimezone(local_tz).replace(hour=23, minute=59, second=0, microsecond=0)
        return None

    def _looks_like_canvas_mail(self, mail: MailItem) -> bool:
        text = f"{mail.subject} {mail.preview} {mail.sender}".lower()
        indicators = [
            "canvas",
            "instructure",
            "submission",
            "assignment",
            "quiz",
            "discussion",
            "course announcement",
            "due",
            "deadline",
        ]
        return any(word in text for word in indicators)

    @staticmethod
    def _is_action_line(line: str) -> bool:
        l = line.strip()
        if len(l) < 4:
            return False
        low = l.lower()
        weak_starts = ("questions?", "cheers", "have a great", "view announcement", "update your notification")
        if any(low.startswith(x) for x in weak_starts):
            return False
        weak_contains = ("links to an external site", "syllabus", "piazza q&a")
        if any(x in low for x in weak_contains):
            return False
        return True

    def _body_has_due_marker(self, body_text: str, now: datetime) -> bool:
        for line in body_text.splitlines():
            ln = line.strip()
            if not ln:
                continue
            low = ln.lower()
            if "due" not in low and "deadline" not in low and "tonight" not in low and "tomorrow" not in low:
                continue
            if self._parse_deadline_from_text(ln, now) is not None:
                return True
        return False

    def _extract_due_blocks(self, mail: MailItem, now: datetime) -> list[TaskItem]:
        text = (mail.body_text or "").strip()
        if not text:
            return []

        lines = [re.sub(r"\s+", " ", ln).strip(" -\t") for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        tasks: list[TaskItem] = []

        for idx, line in enumerate(lines):
            low = line.lower()
            if "due" not in low and "deadline" not in low and "tonight" not in low and "tomorrow" not in low:
                continue
            due_at = self._parse_deadline_from_text(line, now)
            if due_at is None:
                continue

            # Prefer actionable bullet lines immediately after the due marker.
            candidates: list[str] = []
            # Some announcements put task name on the same line after the due timestamp.
            inline_tail = re.split(r"(?:am|pm|AM|PM|central time|ct)\b", line, maxsplit=1)
            if len(inline_tail) > 1:
                tail = inline_tail[1].strip(" -:|")
                if tail and self._is_action_line(tail):
                    candidates.append(tail)
            for j in range(idx + 1, min(idx + 6, len(lines))):
                nxt = lines[j]
                if self._parse_deadline_from_text(nxt, now) is not None:
                    break
                if self._is_action_line(nxt):
                    candidates.append(nxt)

            if not candidates:
                continue

            for cand in candidates[:3]:
                if self.task_mode == "action_only":
                    low_c = cand.lower()
                    if not any(k in low_c for k in self.action_keywords):
                        continue
                tasks.append(
                    TaskItem(
                        source="outlook_canvas_mail",
                        title=self._clean_task_title(cand),
                        due_at=due_at,
                        course=None,
                        url=mail.url,
                        priority=2,
                    )
                )
        return tasks

    def _task_from_mail(self, mail: MailItem, now: datetime) -> TaskItem | None:
        tasks = self._tasks_from_mail(mail, now)
        return tasks[0] if tasks else None

    def _tasks_from_mail(self, mail: MailItem, now: datetime) -> list[TaskItem]:
        if not self._looks_like_canvas_mail(mail):
            return []
        if self._is_noise_mail(mail):
            return []

        block_tasks = self._extract_due_blocks(mail, now)
        if block_tasks:
            return block_tasks
        if self._body_has_due_marker(mail.body_text or "", now):
            return []

        subject = mail.subject.strip()
        preview = mail.preview.strip()
        combined = f"{subject} {preview} {mail.body_text[:1600]}"
        due_at = self._parse_deadline_from_text(combined, now)
        if self.task_mode == "action_only" and not self._is_actionable(mail, due_at):
            return []
        if self.task_require_due and due_at is None:
            return []

        title = subject
        patterns = [
            r"(?:Assignment|作业)\s*[:\-]\s*(.+)",
            r"(?:Due|截止)\s*[:\-]\s*(.+)",
            r"(.+?)\s+(?:is due|due\s+on)",
            r"Submission Reminder\s*[:\-]\s*(.+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, subject, flags=re.IGNORECASE)
            if m:
                title = m.group(1)
                break
        if title == subject and preview:
            preview_match = re.search(r"(?:Assignment|作业)\s*[:\-]\s*(.+?)(?:\.|$)", preview, flags=re.IGNORECASE)
            if preview_match:
                title = preview_match.group(1)

        return [
            TaskItem(
                source="outlook_canvas_mail",
                title=self._clean_task_title(title),
                due_at=due_at,
                course=None,
                url=mail.url,
                priority=2 if due_at else 1,
            )
        ]

    @staticmethod
    def _merge_tasks(primary: list[TaskItem], fallback: list[TaskItem]) -> list[TaskItem]:
        seen: set[str] = set()
        merged: list[TaskItem] = []
        for task in [*primary, *fallback]:
            if DigestService._is_generic_task_title(task.title):
                continue
            due_key = task.due_at.isoformat() if task.due_at else "none"
            key = f"{DigestService._normalize_title_for_key(task.title)}|{due_key}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(task)
        return merged

    @staticmethod
    def _extract_json_object(text: str) -> str:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0) if match else text

    async def _classify_mails_with_llm(self, mails: list[MailItem]) -> dict[int, str]:
        if not self.llm_enabled or not mails:
            return {}

        api_key = self.llm_api_key or (self.llm_client.api_key if self.llm_client else "")
        model = self.llm_model or (self.llm_client.model if self.llm_client else "")
        if not api_key or not model:
            return {}

        payload_mails = []
        for idx, mail in enumerate(mails):
            payload_mails.append(
                {
                    "index": idx,
                    "subject": mail.subject,
                    "sender": mail.sender,
                    "preview": mail.preview[:280],
                    "received_at": mail.received_at.isoformat(),
                }
            )

        system_prompt = (
            "You are an email triage assistant. Classify each mail into exactly one category: "
            "immediate_action, week_todo, info_reference. "
            "Use immediate_action for urgent/deadline-soon tasks, week_todo for actionable work this week, "
            "and info_reference for read-only informational updates. "
            "Return JSON object only, with integer-string index keys and category values."
        )

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload_mails, ensure_ascii=False)},
                        ],
                    },
                )
                response.raise_for_status()
        except Exception:
            return {}

        try:
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(self._extract_json_object(content))
            categories = {"immediate_action", "week_todo", "info_reference"}
            normalized: dict[int, str] = {}
            for raw_idx, raw_bucket in parsed.items():
                bucket = str(raw_bucket).strip()
                if bucket not in categories:
                    continue
                idx = int(raw_idx)
                normalized[idx] = bucket
            return normalized
        except Exception:
            return {}

    def _fallback_mail_bucket(self, mail: MailItem, mail_tasks: list[TaskItem], now: datetime) -> str:
        text = f"{mail.subject} {mail.preview} {mail.body_text[:600]}".lower()
        urgent_keywords = ("urgent", "asap", "immediately", "final notice", "最后提醒", "立即", "马上", "截止")

        due_candidates = [
            task.due_at.astimezone(self.local_tz)
            for task in mail_tasks
            if task.due_at is not None
        ]
        due_at = min(due_candidates) if due_candidates else self._parse_deadline_from_text(text, now)

        if due_at is not None and due_at <= now + timedelta(hours=48):
            return "immediate_action"
        if any(keyword in text for keyword in urgent_keywords):
            return "immediate_action"

        if due_at is not None and due_at <= now + timedelta(days=7):
            return "week_todo"
        if self._is_actionable(mail, due_at) or self._is_mail_important(mail):
            return "week_todo"

        return "info_reference"

    async def _bucket_mails(self, mails: list[MailItem], mail_tasks_by_idx: dict[int, list[TaskItem]], now: datetime) -> MailBuckets:
        llm_result = await self._classify_mails_with_llm(mails)
        buckets = MailBuckets()

        for idx, mail in enumerate(mails):
            bucket = llm_result.get(idx)
            if bucket is None:
                bucket = self._fallback_mail_bucket(mail, mail_tasks_by_idx.get(idx, []), now)

            if bucket == "immediate_action":
                buckets.immediate_action.append(mail)
            elif bucket == "week_todo":
                buckets.week_todo.append(mail)
            else:
                buckets.info_reference.append(mail)

        buckets.immediate_action.sort(key=lambda x: x.received_at, reverse=True)
        buckets.week_todo.sort(key=lambda x: x.received_at, reverse=True)
        buckets.info_reference.sort(key=lambda x: x.received_at, reverse=True)
        return buckets

    def _personalized_push_line(self, push_tasks: list[TaskItem], now: datetime) -> str:
        tone = (self.push_tone or "学姐风").strip()
        is_cute = "可爱" in tone

        first, hours_left, urgency = self._push_context(push_tasks, now)
        if first is None or hours_left is None:
            if is_cute:
                return "可爱提醒: 今天节奏很稳，记得抽 15 分钟整理下本周任务喔。"
            return "学姐提醒: 今天没有紧急截止，建议现在把本周任务先排进日程。"

        if is_cute:
            if urgency == "critical":
                return f"可爱催促: {first.title} 只剩约 {hours_left} 小时啦，先交掉再奖励自己。"
            if urgency == "high":
                return f"可爱提醒: {first.title} 还剩约 {hours_left} 小时，今天优先把它拿下喔。"
            return (
                f"可爱提醒: {first.title} 还剩大约 {hours_left} 小时截止啦，"
                "现在动手最轻松，冲呀。"
            )

        if urgency == "critical":
            return f"学姐催办: {first.title} 距离截止约 {hours_left} 小时，先做完这一项。"
        if urgency == "high":
            return f"学姐提醒: {first.title} 还剩约 {hours_left} 小时，建议今天优先清掉。"
        return (
            f"学姐提醒: {first.title} 距离截止约 {hours_left} 小时，"
            "先把这件事做完，今天就稳了。"
        )

    def _push_context(self, push_tasks: list[TaskItem], now: datetime) -> tuple[TaskItem | None, int | None, str]:
        if not push_tasks:
            return None, None, "none"
        first = min(
            push_tasks,
            key=lambda t: t.due_at.astimezone(self.local_tz) if t.due_at else datetime.max.replace(tzinfo=self.local_tz),
        )
        due_local = first.due_at.astimezone(self.local_tz) if first.due_at else now
        seconds_left = max((due_local - now).total_seconds(), 0)
        hours_left = max(math.ceil(seconds_left / 3600), 0)
        if hours_left <= 6:
            return first, hours_left, "critical"
        if hours_left <= 24:
            return first, hours_left, "high"
        if hours_left <= 48:
            return first, hours_left, "medium"
        return first, hours_left, "low"

    async def build(self) -> DailyDigest:
        now = datetime.now(ZoneInfo(self.timezone_name))
        try:
            mails = await self.outlook_client.fetch_recent_messages()
        except Exception:
            mails = []

        mail_tasks_by_idx: dict[int, list[TaskItem]] = {}
        tasks_from_mail: list[TaskItem] = []
        for idx, mail in enumerate(mails):
            parsed_tasks = self._tasks_from_mail(mail, now)
            mail_tasks_by_idx[idx] = parsed_tasks
            tasks_from_mail.extend(parsed_tasks)

        llm_tasks: list[TaskItem] = []
        if self.llm_enabled and self.llm_client and self.llm_client.is_configured():
            llm_candidates = [m for m in mails if self._looks_like_canvas_mail(m) and not self._is_noise_mail(m)]
            for mail in llm_candidates[: self.llm_max_mails]:
                try:
                    extracted = await self.llm_client.extract_tasks_from_mail(mail, self.timezone_name)
                except Exception:
                    extracted = []
                for task in extracted:
                    if self._is_generic_task_title(task.title):
                        continue
                    if self.task_mode == "action_only":
                        low_t = task.title.lower()
                        if not any(k in low_t for k in self.action_keywords):
                            continue
                        if any(k in low_t for k in self.noise_keywords):
                            continue
                    if self.task_require_due and task.due_at is None:
                        continue
                    if not self._is_due_soon(task, now):
                        continue
                    llm_tasks.append(task)

        canvas_tasks: list[TaskItem] = []
        try:
            canvas_tasks = await self.canvas_client.fetch_todo()
        except Exception:
            # Canvas is optional; mail-derived tasks are the primary source.
            canvas_tasks = []

        tasks = self._merge_tasks(tasks_from_mail, llm_tasks)
        tasks = self._merge_tasks(tasks, canvas_tasks)

        due_tasks = [t for t in tasks if self._is_due_soon(t, now)]
        important_mails = [m for m in mails if self._is_mail_important(m)]
        mail_buckets = await self._bucket_mails(mails, mail_tasks_by_idx, now)

        due_tasks.sort(key=lambda x: x.due_at or datetime.max.replace(tzinfo=self.local_tz))
        important_mails.sort(key=lambda x: x.received_at, reverse=True)

        summary = (
            f"今天有 {len(due_tasks)} 个待办（邮件解析+Canvas可选），"
            f"立刻处理 {len(mail_buckets.immediate_action)} 封，本周待办 {len(mail_buckets.week_todo)} 封。"
        )

        digest = DailyDigest(
            generated_at=now,
            date_label=now.strftime("%Y-%m-%d"),
            tasks=due_tasks,
            important_mails=important_mails,
            mail_buckets=mail_buckets,
            summary_text=summary,
        )
        digest.push_preview = self.to_push_text(digest)
        return digest

    def to_push_text(self, digest: DailyDigest) -> str:
        now = digest.generated_at
        due_limit = now + timedelta(hours=self.push_due_within_hours)
        due_floor = now - timedelta(hours=24)
        push_tasks = []
        for task in digest.tasks:
            if task.due_at is None:
                continue
            due_local = task.due_at.astimezone(self.local_tz)
            if due_floor <= due_local <= due_limit:
                push_tasks.append(task)

        tone = (self.push_tone or "学姐风").strip()
        _, _, urgency = self._push_context(push_tasks, now)
        digest.push_tone = tone
        digest.push_urgency = urgency
        urgency_labels = {
            "none": "无紧急任务",
            "low": "低",
            "medium": "一般",
            "high": "较紧急",
            "critical": "紧急",
        }

        lines = [
            digest.summary_text,
            f"[推送] 风格 {tone} | 紧急度 {urgency_labels.get(urgency, '一般')}",
            self._personalized_push_line(push_tasks, now),
        ]
        for task in push_tasks[:5]:
            due = task.due_at.strftime("%m-%d %H:%M") if task.due_at else "无截止时间"
            lines.append(f"[任务] {task.title} | {due}")

        focus_mails = digest.mail_buckets.immediate_action or digest.important_mails
        for mail in focus_mails[:3]:
            lines.append(f"[邮件] {mail.subject} | {mail.sender}")

        return "\n".join(lines)
