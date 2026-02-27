from __future__ import annotations

from datetime import datetime, timezone
import re
import time
from urllib.parse import urlencode
import httpx

from app.models import MailItem
from app.services.token_store import TokenStore


class OutlookClient:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        user_email: str,
        redirect_uri: str,
        token_store_path: str,
        cache_ttl_sec: int = 60,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_email = user_email
        self.redirect_uri = redirect_uri
        self.token_store = TokenStore(token_store_path)
        self.scope = "offline_access Mail.Read User.Read openid profile"
        self.cache_ttl_sec = max(cache_ttl_sec, 0)
        self._messages_cache: dict[int, tuple[float, list[MailItem]]] = {}

    def is_configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.redirect_uri)

    def is_connected(self) -> bool:
        data = self.token_store.load() or {}
        return bool(data.get("refresh_token") or data.get("access_token"))

    def get_authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "response_mode": "query",
                "scope": self.scope,
                "state": state,
            }
        )
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize?{query}"

    @staticmethod
    def _normalize_token(payload: dict) -> dict:
        now = int(time.time())
        expires_in = int(payload.get("expires_in", 0))
        payload["expires_at"] = now + max(expires_in - 60, 0)
        return payload

    async def exchange_code(self, code: str) -> None:
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(token_url, data=payload)
            resp.raise_for_status()
            self.token_store.save(self._normalize_token(resp.json()))

    async def _refresh_access_token(self, refresh_token: str) -> str | None:
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": self.scope,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(token_url, data=payload)
            if resp.status_code >= 400:
                return None
            token_data = self._normalize_token(resp.json())
            if "refresh_token" not in token_data:
                token_data["refresh_token"] = refresh_token
            self.token_store.save(token_data)
            return token_data.get("access_token")

    async def _get_access_token(self) -> str | None:
        if not self.is_configured():
            return None
        token_data = self.token_store.load() or {}
        now = int(time.time())
        access_token = token_data.get("access_token")
        expires_at = int(token_data.get("expires_at", 0))
        if access_token and expires_at > now:
            return access_token

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return None
        return await self._refresh_access_token(refresh_token)

    def _cache_get(self, max_count: int) -> list[MailItem] | None:
        if self.cache_ttl_sec <= 0:
            return None
        hit = self._messages_cache.get(max_count)
        if not hit:
            return None
        ts, rows = hit
        if time.time() - ts > self.cache_ttl_sec:
            self._messages_cache.pop(max_count, None)
            return None
        return rows

    def _cache_set(self, max_count: int, rows: list[MailItem]) -> None:
        if self.cache_ttl_sec <= 0:
            return
        self._messages_cache[max_count] = (time.time(), rows)

    async def _fetch_messages_rows(self, token: str, max_count: int) -> list[dict]:
        graph_url = (
            "https://graph.microsoft.com/v1.0/me/messages"
            f"?$top={max_count}"
            "&$orderby=receivedDateTime desc"
            "&$select=subject,from,bodyPreview,body,receivedDateTime,importance,webLink"
        )
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(graph_url, headers=headers)
            if resp.status_code == 401:
                token_data = self.token_store.load() or {}
                refreshed = await self._refresh_access_token(token_data.get("refresh_token", ""))
                if not refreshed:
                    self.token_store.clear()
                    return []
                headers = {"Authorization": f"Bearer {refreshed}"}
                resp = await client.get(graph_url, headers=headers)
            resp.raise_for_status()
            return resp.json().get("value", [])

    async def fetch_recent_messages(self, max_count: int = 20, use_cache: bool = True) -> list[MailItem]:
        if use_cache:
            cached = self._cache_get(max_count)
            if cached is not None:
                return cached

        token = await self._get_access_token()
        if not token:
            return []

        rows = await self._fetch_messages_rows(token, max_count)

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
                    body_text=self._strip_html(((row.get("body") or {}).get("content") or "")),
                    is_important=(row.get("importance") or "").lower() == "high",
                    url=row.get("webLink"),
                )
            )

        self._cache_set(max_count, items)
        return items

    def disconnect(self) -> None:
        self.token_store.clear()
        self._messages_cache.clear()

    @staticmethod
    def _strip_html(html: str) -> str:
        if not html:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"</p>|</div>|</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()
