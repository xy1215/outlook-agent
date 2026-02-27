from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo
import httpx

from app.models import TaskItem


class CanvasClient:
    def __init__(self, base_url: str, token: str, calendar_feed_url: str = "", timezone_name: str = "America/Los_Angeles") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.calendar_feed_url = (calendar_feed_url or "").strip()
        self.timezone_name = timezone_name

    @staticmethod
    def _decode_ics_text(value: str) -> str:
        # ICS may escape commas, semicolons and newlines.
        return value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()

    @staticmethod
    def _extract_url(text: str) -> str | None:
        m = re.search(r"https?://[^\s>]+", text or "")
        return m.group(0) if m else None

    def _parse_ics_dt(self, raw: str, is_all_day: bool = False) -> datetime | None:
        value = (raw or "").strip()
        if not value:
            return None
        try:
            if len(value) == 8 and value.isdigit():
                base = datetime.strptime(value, "%Y%m%d")
                if is_all_day:
                    base = base.replace(hour=23, minute=59, second=0, microsecond=0)
                return base.replace(tzinfo=ZoneInfo(self.timezone_name))
            if value.endswith("Z"):
                return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC"))
            return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(self.timezone_name))
        except ValueError:
            return None

    @staticmethod
    def _unfold_ics_lines(text: str) -> list[str]:
        lines: list[str] = []
        for raw in text.splitlines():
            line = raw.rstrip("\r")
            if not line:
                continue
            if line.startswith((" ", "\t")) and lines:
                lines[-1] += line[1:]
                continue
            lines.append(line)
        return lines

    def _parse_ics_tasks(self, text: str) -> list[TaskItem]:
        lines = self._unfold_ics_lines(text)
        tasks: list[TaskItem] = []
        in_event = False
        fields: dict[str, tuple[str, str]] = {}

        def flush_event() -> None:
            if not fields:
                return
            summary = self._decode_ics_text(fields.get("SUMMARY", ("", ""))[1]) or "Canvas calendar item"
            dtstart_params, dtstart_raw = fields.get("DTSTART", ("", ""))
            dtend_params, dtend_raw = fields.get("DTEND", ("", ""))
            due_at = self._parse_ics_dt(dtstart_raw, "VALUE=DATE" in dtstart_params)
            if due_at is None and dtend_raw:
                due_at = self._parse_ics_dt(dtend_raw, "VALUE=DATE" in dtend_params)
            if due_at is None:
                return
            created_params, created_raw = fields.get("CREATED", ("", ""))
            published_at = self._parse_ics_dt(created_raw, "VALUE=DATE" in created_params)
            description = self._decode_ics_text(fields.get("DESCRIPTION", ("", ""))[1])
            explicit_url = self._decode_ics_text(fields.get("URL", ("", ""))[1])
            url = explicit_url or self._extract_url(description)
            course = self._decode_ics_text(fields.get("CATEGORIES", ("", ""))[1]) or None
            tasks.append(
                TaskItem(
                    source="canvas_feed",
                    title=summary,
                    due_at=due_at,
                    published_at=published_at,
                    course=course,
                    url=url,
                    priority=2,
                )
            )

        for line in lines:
            if line == "BEGIN:VEVENT":
                in_event = True
                fields = {}
                continue
            if line == "END:VEVENT":
                flush_event()
                in_event = False
                fields = {}
                continue
            if not in_event or ":" not in line:
                continue
            left, value = line.split(":", 1)
            parts = left.split(";", 1)
            key = parts[0].upper()
            params = parts[1].upper() if len(parts) > 1 else ""
            if key in {"SUMMARY", "DTSTART", "DTEND", "DESCRIPTION", "URL", "CREATED", "CATEGORIES"}:
                fields[key] = (params, value)
        return tasks

    @staticmethod
    def _merge_tasks(primary: list[TaskItem], secondary: list[TaskItem]) -> list[TaskItem]:
        merged: list[TaskItem] = []
        seen: set[str] = set()
        for task in [*primary, *secondary]:
            due_key = task.due_at.isoformat() if task.due_at else "none"
            key = f"{task.title.strip().lower()}|{due_key}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(task)
        return merged

    async def _fetch_canvas_api_todo(self) -> list[TaskItem]:
        if not self.base_url or not self.token:
            return []
        url = f"{self.base_url}/api/v1/users/self/todo"
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            rows = resp.json()

        items: list[TaskItem] = []
        for row in rows:
            assignment = row.get("assignment") or {}
            due_at = assignment.get("due_at")
            published = assignment.get("created_at") or row.get("created_at")
            items.append(
                TaskItem(
                    source="canvas",
                    title=assignment.get("name") or row.get("type", "Untitled task"),
                    due_at=datetime.fromisoformat(due_at.replace("Z", "+00:00")) if due_at else None,
                    published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if isinstance(published, str) and published else None,
                    course=(row.get("context_name") or row.get("course") or "").strip() or None,
                    url=assignment.get("html_url") or row.get("html_url"),
                    priority=2,
                )
            )
        return items

    async def _fetch_canvas_feed_todo(self) -> list[TaskItem]:
        if not self.calendar_feed_url:
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(self.calendar_feed_url)
            resp.raise_for_status()
        return self._parse_ics_tasks(resp.text)

    async def fetch_todo(self) -> list[TaskItem]:
        api_tasks: list[TaskItem] = []
        feed_tasks: list[TaskItem] = []
        try:
            api_tasks = await self._fetch_canvas_api_todo()
        except Exception:
            api_tasks = []
        try:
            feed_tasks = await self._fetch_canvas_feed_todo()
        except Exception:
            feed_tasks = []
        return self._merge_tasks(api_tasks, feed_tasks)
