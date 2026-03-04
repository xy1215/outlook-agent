from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
import secrets
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import DailyDigest
from app.scheduler import create_scheduler, daily_trigger, parse_schedule_time
from app.services.canvas_client import CanvasClient
from app.services.digest_service import DigestService
from app.services.mail_classifier import MailClassifier
from app.services.notifier import Notifier
from app.services.outlook_client import OutlookClient
from app.services.run_state import RunStateStore

canvas_client = CanvasClient(
    settings.canvas_base_url,
    settings.canvas_token,
    settings.canvas_calendar_feed_url,
    settings.timezone,
    settings.canvas_feed_cache_path,
    settings.canvas_feed_refresh_hours,
)
outlook_client = OutlookClient(
    settings.ms_tenant_id,
    settings.ms_client_id,
    settings.ms_client_secret,
    settings.ms_user_email,
    settings.ms_redirect_uri,
    settings.ms_token_store_path,
)
notifier = Notifier(settings.push_provider, settings.pushover_app_token, settings.pushover_user_key)
mail_classifier = MailClassifier(
    timezone_name=settings.timezone,
    llm_api_base=settings.llm_api_base,
    llm_api_key=settings.llm_api_key,
    llm_model=settings.llm_model,
    llm_timeout_sec=settings.llm_timeout_sec,
    llm_max_parallel=settings.llm_max_parallel,
    llm_enabled=settings.llm_mail_enabled,
    llm_max_calls_per_run=settings.llm_mail_max_calls_per_run,
    llm_fail_fast_threshold=settings.llm_fail_fast_threshold,
    llm_cache_ttl_hours=settings.llm_cache_ttl_hours,
    llm_cache_path=settings.llm_mail_cache_path,
)
digest_service = DigestService(
    canvas_client,
    outlook_client,
    settings.timezone,
    settings.digest_lookahead_days,
    settings.important_keywords,
    settings.task_require_due,
    settings.push_due_within_hours,
    settings.push_persona,
    mail_classifier,
    settings.llm_api_base,
    settings.llm_api_key,
    settings.llm_model,
    settings.llm_timeout_sec,
    settings.llm_max_parallel,
    settings.llm_canvas_max_calls_per_run,
    settings.llm_fail_fast_threshold,
    settings.llm_cache_ttl_hours,
    settings.llm_canvas_cache_path,
)
scheduler = create_scheduler(settings.timezone)
latest_digest: DailyDigest | None = None
oauth_state: Optional[str] = None
started_at = datetime.now(timezone.utc)
run_state_store = RunStateStore(settings.run_state_path)


async def run_daily_job(*, force_canvas_refresh: bool = True) -> dict:
    global latest_digest
    now = datetime.now(ZoneInfo(settings.timezone))
    try:
        digest = await digest_service.build(force_canvas_refresh=force_canvas_refresh)
        latest_digest = digest
        await notifier.send("校园每日提醒", digest_service.to_push_text(digest))
        run_state_store.record(push_sent=True, error=None, run_at=now)
        return {"push_sent": True, "run_at": now.isoformat()}
    except Exception as exc:
        run_state_store.record(push_sent=False, error=str(exc), run_at=now)
        return {"push_sent": False, "error": str(exc), "run_at": now.isoformat()}


def _should_backfill_push(now_local: datetime) -> bool:
    state = run_state_store.load()
    hour, minute = parse_schedule_time(settings.schedule_time)
    schedule_dt = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_local < schedule_dt:
        return False
    raw = state.get("last_success_at")
    if not isinstance(raw, str) or not raw:
        return True
    try:
        last_success = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=ZoneInfo(settings.timezone))
    return last_success.astimezone(ZoneInfo(settings.timezone)).date() < now_local.date()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(run_daily_job, daily_trigger(settings.schedule_time, settings.timezone), id="daily_digest", replace_existing=True)
    scheduler.start()
    now_local = datetime.now(ZoneInfo(settings.timezone))
    if _should_backfill_push(now_local):
        asyncio.create_task(run_daily_job(force_canvas_refresh=True))
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Campus Daily Agent", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "schedule_time": settings.schedule_time, "timezone": settings.timezone})


@app.get("/api/auth-status")
async def auth_status() -> dict:
    return {
        "configured": outlook_client.is_configured(),
        "connected": outlook_client.is_connected(),
    }


@app.get("/api/health")
async def health() -> dict:
    state = run_state_store.load()
    return {
        "ok": True,
        "pid": os.getpid(),
        "started_at_utc": started_at.isoformat(),
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "last_run_at": state.get("last_run_at", ""),
        "last_success_at": state.get("last_success_at", ""),
        "last_error": state.get("last_error", ""),
    }


@app.get("/auth/login")
async def auth_login() -> RedirectResponse:
    global oauth_state
    if not outlook_client.is_configured():
        return RedirectResponse(url="/?auth=not-configured")
    oauth_state = secrets.token_urlsafe(24)
    return RedirectResponse(url=outlook_client.get_authorize_url(oauth_state))


@app.get("/auth/callback")
async def auth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None) -> RedirectResponse:
    global oauth_state
    if error:
        return RedirectResponse(url=f"/?auth=error&reason={error}")
    if not code:
        return RedirectResponse(url="/?auth=error&reason=missing_code")
    if oauth_state and state != oauth_state:
        return RedirectResponse(url="/?auth=error&reason=state_mismatch")
    try:
        await outlook_client.exchange_code(code)
    except Exception:
        return RedirectResponse(url="/?auth=error&reason=token_exchange_failed")
    finally:
        oauth_state = None
    return RedirectResponse(url="/?auth=ok")


@app.post("/auth/logout")
async def auth_logout() -> dict:
    global latest_digest
    outlook_client.disconnect()
    latest_digest = None
    return {"ok": True}


@app.get("/api/today")
async def get_today(refresh: bool = False) -> dict:
    global latest_digest
    tz = ZoneInfo(settings.timezone)
    stale_for_today = latest_digest is not None and latest_digest.generated_at.astimezone(tz).date() < datetime.now(tz).date()
    if refresh or latest_digest is None or stale_for_today:
        latest_digest = await digest_service.build(force_canvas_refresh=bool(refresh or stale_for_today))
    return latest_digest.model_dump(mode="json")


@app.post("/api/run-now")
async def run_now() -> dict:
    result = await run_daily_job(force_canvas_refresh=True)
    return {"ok": True, "message": "Manual run completed.", **result}
