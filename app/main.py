from __future__ import annotations

import secrets
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import DailyDigest
from app.scheduler import create_scheduler, daily_trigger
from app.services.canvas_client import CanvasClient
from app.services.digest_service import DigestService
from app.services.mail_classifier import MailClassifier
from app.services.notifier import Notifier
from app.services.outlook_client import OutlookClient

app = FastAPI(title="Campus Daily Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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
    settings.llm_cache_ttl_hours,
    settings.llm_canvas_cache_path,
)
scheduler = create_scheduler(settings.timezone)
latest_digest: DailyDigest | None = None
oauth_state: Optional[str] = None


async def run_daily_job() -> dict:
    global latest_digest
    digest = await digest_service.build()
    latest_digest = digest
    try:
        await notifier.send("校园每日提醒", digest_service.to_push_text(digest))
        return {"push_sent": True}
    except Exception as exc:
        return {"push_sent": False, "error": str(exc)}


@app.on_event("startup")
async def startup_event() -> None:
    scheduler.add_job(run_daily_job, daily_trigger(settings.schedule_time, settings.timezone), id="daily_digest", replace_existing=True)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    scheduler.shutdown(wait=False)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "schedule_time": settings.schedule_time, "timezone": settings.timezone})


@app.get("/api/auth-status")
async def auth_status() -> dict:
    return {
        "configured": outlook_client.is_configured(),
        "connected": outlook_client.is_connected(),
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
    if refresh or latest_digest is None:
        latest_digest = await digest_service.build()
    return latest_digest.model_dump(mode="json")


@app.post("/api/run-now")
async def run_now() -> dict:
    result = await run_daily_job()
    return {"ok": True, "message": "Manual run completed.", **result}
