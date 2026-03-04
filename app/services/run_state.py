from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class RunStateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def record(self, *, run_at: datetime, push_sent: bool, error: str | None = None) -> None:
        state = self.load()
        run_at_iso = run_at.isoformat()
        state["last_run_at"] = run_at_iso
        state["last_error"] = error
        if push_sent:
            state["last_success_at"] = run_at_iso
            state["last_push_at"] = run_at_iso
            state["last_push_date"] = run_at.date().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
