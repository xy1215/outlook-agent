from __future__ import annotations

import json
from pathlib import Path


class TokenStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save(self, token_data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(token_data), encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
