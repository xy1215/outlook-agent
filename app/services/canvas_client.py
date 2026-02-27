from __future__ import annotations

from datetime import datetime
import httpx

from app.models import TaskItem


class CanvasClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def fetch_todo(self) -> list[TaskItem]:
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
