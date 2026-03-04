from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


class RunStateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def record(self, *, push_sent: bool, error: str | None, run_at: datetime) -> dict[str, Any]:
        current = self.load()
        current["last_run_at"] = run_at.isoformat()
        current["last_push_sent"] = bool(push_sent)
        current["last_error"] = error or ""
        if push_sent:
            current["last_success_at"] = run_at.isoformat()
        self.save(current)
        return current
