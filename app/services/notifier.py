from __future__ import annotations

import httpx


class Notifier:
    def __init__(self, provider: str, app_token: str, user_key: str) -> None:
        self.provider = provider
        self.app_token = app_token
        self.user_key = user_key

    async def send(self, title: str, message: str) -> None:
        if self.provider != "pushover":
            raise ValueError(f"Unsupported provider: {self.provider}")
        if not self.app_token or not self.user_key:
            raise ValueError("Pushover credentials are missing")

        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": self.app_token,
            "user": self.user_key,
            "title": title,
            "message": message,
            "priority": 0,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, data=payload)
            resp.raise_for_status()
