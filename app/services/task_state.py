from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from app.models import DailyDigest, TaskItem


def task_id(task: TaskItem) -> str:
    raw = "|".join(
        [
            (task.title or "").strip().lower(),
            task.due_at.isoformat() if task.due_at else "",
            (task.course or "").strip().lower(),
            (task.url or "").strip().lower(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def remaining_text(task: TaskItem, now: datetime) -> str:
    if task.due_at is None:
        return "无截止时间"
    diff = task.due_at - now
    total_minutes = int(abs(diff.total_seconds()) // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if diff.total_seconds() >= 0:
        return f"剩余 {hours} 小时 {minutes} 分钟"
    return f"已超时 {hours} 小时 {minutes} 分钟"


class TaskStateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {"tasks": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("tasks"), dict):
                return payload
        except Exception:
            pass
        return {"tasks": {}}

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _entry(self, tid: str) -> dict:
        state = self.load()
        tasks = state.setdefault("tasks", {})
        row = tasks.get(tid)
        if not isinstance(row, dict):
            row = {}
            tasks[tid] = row
        return row

    def is_done(self, tid: str) -> bool:
        row = self.load().get("tasks", {}).get(tid, {})
        return bool(row.get("done_at"))

    def snoozed_until(self, tid: str) -> datetime | None:
        row = self.load().get("tasks", {}).get(tid, {})
        raw = row.get("snoozed_until")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def is_snoozed(self, tid: str, now: datetime) -> bool:
        until = self.snoozed_until(tid)
        return until is not None and until > now

    def mark_done(self, tid: str, now: datetime) -> None:
        state = self.load()
        tasks = state.setdefault("tasks", {})
        row = tasks.setdefault(tid, {})
        row["done_at"] = now.isoformat()
        row["snoozed_until"] = ""
        self.save(state)

    def snooze_hours(self, tid: str, hours: int, now: datetime) -> datetime:
        until = now + timedelta(hours=max(1, hours))
        state = self.load()
        tasks = state.setdefault("tasks", {})
        row = tasks.setdefault(tid, {})
        row["snoozed_until"] = until.isoformat()
        # Unsnooze should also clear done mark if existed.
        row["done_at"] = ""
        self.save(state)
        return until

    def apply(self, digest: DailyDigest, now: datetime) -> DailyDigest:
        kept = []
        for task in digest.tasks:
            tid = task_id(task)
            if self.is_done(tid):
                continue
            if self.is_snoozed(tid, now):
                continue
            kept.append(task)
        return digest.model_copy(update={"tasks": kept})

