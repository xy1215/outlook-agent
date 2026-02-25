from __future__ import annotations

from datetime import datetime, timezone
import httpx

from app.models import MailItem


class OutlookClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, user_email: str) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_email = user_email

    async def _get_token(self) -> str:
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(token_url, data=payload)
            resp.raise_for_status()
            return resp.json()["access_token"]

    async def fetch_recent_messages(self, max_count: int = 20) -> list[MailItem]:
        token = await self._get_token()
        now = datetime.now(timezone.utc).isoformat()
        graph_url = (
            f"https://graph.microsoft.com/v1.0/users/{self.user_email}/messages"
            f"?$top={max_count}"
            f"&$filter=receivedDateTime le {now}"
            "&$orderby=receivedDateTime desc"
            "&$select=subject,from,bodyPreview,receivedDateTime,importance,webLink"
        )
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(graph_url, headers=headers)
            resp.raise_for_status()
            rows = resp.json().get("value", [])

        items: list[MailItem] = []
        for row in rows:
            sender = (((row.get("from") or {}).get("emailAddress") or {}).get("address") or "unknown")
            received = row.get("receivedDateTime")
            items.append(
                MailItem(
                    subject=row.get("subject") or "(no subject)",
                    sender=sender,
                    received_at=datetime.fromisoformat(received.replace("Z", "+00:00")) if received else datetime.now(timezone.utc),
                    preview=(row.get("bodyPreview") or "")[:240],
                    is_important=(row.get("importance") or "").lower() == "high",
                    url=row.get("webLink"),
                )
            )
        return items
