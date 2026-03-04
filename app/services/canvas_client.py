from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import httpx

from app.models import TaskItem


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        calendar_feed_url: str = "",
        timezone_name: str = "America/Los_Angeles",
        feed_cache_path: str = "data/canvas_feed_cache.json",
        feed_refresh_hours: int = 24,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.calendar_feed_url = (calendar_feed_url or "").strip()
        self.timezone_name = timezone_name
        self.feed_cache_path = Path(feed_cache_path)
        self.feed_refresh_hours = max(1, feed_refresh_hours)

    @staticmethod
    def _decode_ics_text(value: str) -> str:
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
                    details=description or None,
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
    def _serialize_task(task: TaskItem) -> dict:
        return task.model_dump(mode="json")

    @staticmethod
    def _deserialize_task(row: dict) -> TaskItem | None:
        try:
            return TaskItem.model_validate(row)
        except Exception:
            return None

    def _load_cache(self) -> tuple[datetime | None, list[TaskItem]]:
        if not self.feed_cache_path.exists():
            return None, []
        try:
            payload = json.loads(self.feed_cache_path.read_text(encoding="utf-8"))
            fetched_at_raw = payload.get("fetched_at")
            fetched_at = datetime.fromisoformat(fetched_at_raw) if isinstance(fetched_at_raw, str) else None
            tasks = []
            for row in payload.get("tasks", []):
                task = self._deserialize_task(row)
                if task is not None:
                    tasks.append(task)
            return fetched_at, tasks
        except Exception:
            return None, []

    def _save_cache(self, fetched_at: datetime, tasks: list[TaskItem]) -> None:
        self.feed_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": fetched_at.isoformat(),
            "tasks": [self._serialize_task(task) for task in tasks],
        }
        self.feed_cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _fetch_canvas_feed_now(self) -> list[TaskItem]:
        if not self.calendar_feed_url:
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(self.calendar_feed_url)
            resp.raise_for_status()
        return self._parse_ics_tasks(resp.text)

    async def fetch_todo(self) -> list[TaskItem]:
        if not self.calendar_feed_url:
            return []

        now = datetime.now(ZoneInfo("UTC"))
        fetched_at, cached_tasks = self._load_cache()
        if fetched_at is not None and now - fetched_at < timedelta(hours=self.feed_refresh_hours):
            return cached_tasks

        try:
            fresh_tasks = await self._fetch_canvas_feed_now()
            self._save_cache(now, fresh_tasks)
            return fresh_tasks
        except Exception:
            return cached_tasks
