from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import DailyDigest
from app.scheduler import create_scheduler, daily_trigger
from app.services.canvas_client import CanvasClient
from app.services.digest_service import DigestService
from app.services.notifier import Notifier
from app.services.outlook_client import OutlookClient

app = FastAPI(title="Campus Daily Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

canvas_client = CanvasClient(settings.canvas_base_url, settings.canvas_token)
outlook_client = OutlookClient(
    settings.ms_tenant_id,
    settings.ms_client_id,
    settings.ms_client_secret,
    settings.ms_user_email,
)
notifier = Notifier(settings.push_provider, settings.pushover_app_token, settings.pushover_user_key)
digest_service = DigestService(
    canvas_client,
    outlook_client,
    settings.timezone,
    settings.digest_lookahead_days,
    settings.important_keywords,
)
scheduler = create_scheduler(settings.timezone)
latest_digest: DailyDigest | None = None


async def run_daily_job() -> None:
    global latest_digest
    digest = await digest_service.build()
    latest_digest = digest
    await notifier.send("校园每日提醒", DigestService.to_push_text(digest))


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


@app.get("/api/today")
async def get_today() -> dict:
    global latest_digest
    if latest_digest is None:
        latest_digest = await digest_service.build()
    return latest_digest.model_dump(mode="json")


@app.post("/api/run-now")
async def run_now() -> dict:
    await run_daily_job()
    return {"ok": True, "message": "Manual run completed and push sent."}
