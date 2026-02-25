from __future__ import annotations

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from app.models import DailyDigest, MailItem, TaskItem
from app.services.canvas_client import CanvasClient
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
        task_action_keywords: str = "due,deadline,exam,quiz,submission,homework,hw,project,midterm,final",
        task_noise_keywords: str = "assignment graded,graded:,office hours moved,daily digest,piazza,announcement posted",
        task_require_due: bool = True,
        push_due_within_hours: int = 48,
    ) -> None:
        self.canvas_client = canvas_client
        self.outlook_client = outlook_client
        self.timezone_name = timezone_name
        self.lookahead_days = lookahead_days
        self.keywords = [k.strip().lower() for k in important_keywords.split(",") if k.strip()]
        self.task_mode = (task_mode or "action_only").strip().lower()
        self.action_keywords = [k.strip().lower() for k in task_action_keywords.split(",") if k.strip()]
        self.noise_keywords = [k.strip().lower() for k in task_noise_keywords.split(",") if k.strip()]
        self.task_require_due = task_require_due
        self.push_due_within_hours = push_due_within_hours

    def _is_due_soon(self, task: TaskItem, now: datetime) -> bool:
        if task.due_at is None:
            return not self.task_require_due
        due_local = task.due_at.astimezone(ZoneInfo(self.timezone_name))
        return due_local <= now + timedelta(days=self.lookahead_days)

    def _is_mail_important(self, mail: MailItem) -> bool:
        if mail.is_important:
            return True
        text = f"{mail.subject} {mail.preview}".lower()
        return any(keyword in text for keyword in self.keywords)

    def _is_noise_mail(self, mail: MailItem) -> bool:
        text = f"{mail.subject} {mail.preview}".lower()
        return any(keyword in text for keyword in self.noise_keywords)

    def _is_actionable(self, mail: MailItem, due_at: datetime | None) -> bool:
        if due_at is not None:
            return True
        text = f"{mail.subject} {mail.preview}".lower()
        return any(keyword in text for keyword in self.action_keywords)

    @staticmethod
    def _clean_task_title(raw: str) -> str:
        text = re.sub(r"\s+", " ", raw).strip(" -:|")
        return text or "Canvas task"

    def _parse_deadline_from_text(self, text: str, now: datetime) -> datetime | None:
        local_tz = ZoneInfo(self.timezone_name)
        text_l = text.lower()

        rel_match = re.search(r"\b(today|tomorrow)\b(?:\s+(?:at\s+)?)?(\d{1,2}:\d{2})?\s*(am|pm|AM|PM)?", text)
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
        iso_match = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})(?:\s+(\d{1,2}:\d{2}))?", text)
        if iso_match:
            date_part = iso_match.group(1)
            time_part = iso_match.group(2) or "23:59"
            try:
                return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M").replace(tzinfo=local_tz)
            except ValueError:
                pass

        # US-like: 3/8 11:59 PM, 03/08/2026, 3/8
        us_match = re.search(r"(\d{1,2}/\d{1,2})(?:/(\d{2,4}))?(?:\s+(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?)?", text)
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
                if not year_part and parsed < now - timedelta(days=1):
                    parsed = parsed.replace(year=year + 1)
                return parsed
            except ValueError:
                pass

        # Month words: Mar 8, March 8 11:59 PM
        month_match = re.search(
            r"\b("
            r"Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|"
            r"Oct|October|Nov|November|Dec|December"
            r")\s+(\d{1,2})(?:,\s*(20\d{2}))?(?:\s+(?:at\s+)?(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?)?",
            text,
        )
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
                if not month_match.group(3) and parsed < now - timedelta(days=1):
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

    def _task_from_mail(self, mail: MailItem, now: datetime) -> TaskItem | None:
        if not self._looks_like_canvas_mail(mail):
            return None
        if self._is_noise_mail(mail):
            return None

        subject = mail.subject.strip()
        preview = mail.preview.strip()
        combined = f"{subject} {preview}"
        due_at = self._parse_deadline_from_text(combined, now)
        if self.task_mode == "action_only" and not self._is_actionable(mail, due_at):
            return None
        if self.task_require_due and due_at is None:
            return None

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

        return TaskItem(
            source="outlook_canvas_mail",
            title=self._clean_task_title(title),
            due_at=due_at,
            course=None,
            url=mail.url,
            priority=2 if due_at else 1,
        )

    @staticmethod
    def _merge_tasks(primary: list[TaskItem], fallback: list[TaskItem]) -> list[TaskItem]:
        seen: set[str] = set()
        merged: list[TaskItem] = []
        for task in [*primary, *fallback]:
            due_key = task.due_at.isoformat() if task.due_at else "none"
            key = f"{task.title.lower()}|{due_key}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(task)
        return merged

    async def build(self) -> DailyDigest:
        now = datetime.now(ZoneInfo(self.timezone_name))
        try:
            mails = await self.outlook_client.fetch_recent_messages()
        except Exception:
            mails = []
        tasks_from_mail = [t for t in (self._task_from_mail(mail, now) for mail in mails) if t is not None]

        canvas_tasks: list[TaskItem] = []
        try:
            canvas_tasks = await self.canvas_client.fetch_todo()
        except Exception:
            # Canvas is optional; mail-derived tasks are the primary source.
            canvas_tasks = []

        tasks = self._merge_tasks(tasks_from_mail, canvas_tasks)

        due_tasks = [t for t in tasks if self._is_due_soon(t, now)]
        important_mails = [m for m in mails if self._is_mail_important(m)]

        due_tasks.sort(key=lambda x: x.due_at or datetime.max.replace(tzinfo=ZoneInfo(self.timezone_name)))
        important_mails.sort(key=lambda x: x.received_at, reverse=True)

        summary = (
            f"今天有 {len(due_tasks)} 个待办（邮件解析+Canvas可选），"
            f"{len(important_mails)} 封重要邮件（Outlook）。"
        )

        return DailyDigest(
            generated_at=now,
            date_label=now.strftime("%Y-%m-%d"),
            tasks=due_tasks,
            important_mails=important_mails,
            summary_text=summary,
        )

    def to_push_text(self, digest: DailyDigest) -> str:
        now = digest.generated_at
        due_limit = now + timedelta(hours=self.push_due_within_hours)
        due_floor = now - timedelta(hours=24)
        push_tasks = []
        for task in digest.tasks:
            if task.due_at is None:
                continue
            due_local = task.due_at.astimezone(ZoneInfo(self.timezone_name))
            if due_floor <= due_local <= due_limit:
                push_tasks.append(task)

        lines = [digest.summary_text]
        for task in push_tasks[:5]:
            due = task.due_at.strftime("%m-%d %H:%M") if task.due_at else "无截止时间"
            lines.append(f"[任务] {task.title} | {due}")
        for mail in digest.important_mails[:3]:
            lines.append(f"[邮件] {mail.subject} | {mail.sender}")
        return "\n".join(lines)
