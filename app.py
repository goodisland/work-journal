from __future__ import annotations

import os
from datetime import date, datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from recorder import RecorderService
from reporter import build_artifact_groups, build_private_summary, build_public_report
from sample_data import ensure_sample_data
from storage import BASE_DIR, ensure_directories, read_logs
from task_manager import TaskService


load_dotenv(override=True)
ensure_directories()
ensure_sample_data()

app = FastAPI(title="Work Journal Mock")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/data", StaticFiles(directory=str(BASE_DIR / "data")), name="data")

task_service = TaskService()
recorder_service = RecorderService(
    interval_seconds=int(os.getenv("CAPTURE_INTERVAL_SECONDS", "60")),
    enable_ocr=os.getenv("OCR_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
    use_ai=os.getenv("AI_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
    ai_provider=os.getenv("AI_PROVIDER", "mock"),
    ai_threshold=float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.6")),
    task_context_provider=task_service.get_task_context,
)


def empty_summary() -> dict:
    return {
        "total_minutes": 0,
        "totals": [],
        "timeline": [],
        "top_labels": [],
        "long_running": [],
        "busy_hours": [],
        "transition_count": 0,
        "suggestions": [],
        "task_totals": [],
        "artifact_count": 0,
        "manual_capture_count": 0,
    }


def get_today_logs() -> list[dict]:
    return read_logs(target_date=date.today())


def get_today_sessions() -> list[dict]:
    return task_service.list_sessions_for_date(target_date=date.today())


def get_today_summary() -> dict:
    entries = get_today_logs()
    sessions = get_today_sessions()
    return build_private_summary(entries, sessions=sessions) if entries or sessions else empty_summary()


def build_base_context(request: Request) -> dict:
    active_session = task_service.get_active_session()
    return {
        "request": request,
        "recording": recorder_service.is_running,
        "active_session": active_session,
        "task_options": task_service.build_task_options(),
        "task_groups": task_service.build_task_groups(),
        "now_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    entries = get_today_logs()
    sessions = get_today_sessions()
    context = build_base_context(request)
    context.update(
        {
            "entries": entries,
            "sessions": sessions,
            "summary": build_private_summary(entries, sessions=sessions) if entries or sessions else empty_summary(),
            "settings": {
                "interval_seconds": recorder_service.interval_seconds,
                "enable_ocr": recorder_service.enable_ocr,
                "use_ai": recorder_service.use_ai,
                "ai_provider": recorder_service.ai_provider,
                "ai_threshold": recorder_service.ai_threshold,
            },
        }
    )
    return templates.TemplateResponse("index.html", context)


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    context = build_base_context(request)
    context.update(
        {
            "level_options": task_service.get_level_options(),
            "editing_task": None,
        }
    )
    return templates.TemplateResponse("tasks.html", context)


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_page(request: Request, task_id: str):
    context = build_base_context(request)
    context.update(
        {
            "level_options": task_service.get_level_options(),
            "editing_task": task_service.get_task(task_id),
        }
    )
    return templates.TemplateResponse("tasks.html", context)


@app.get("/timeline", response_class=HTMLResponse)
def timeline(request: Request):
    entries = list(reversed(get_today_logs()))
    context = build_base_context(request)
    context.update({"entries": entries})
    return templates.TemplateResponse("timeline.html", context)


@app.get("/private-summary", response_class=HTMLResponse)
def private_summary(request: Request):
    entries = get_today_logs()
    sessions = get_today_sessions()
    context = build_base_context(request)
    context.update(
        {
            "summary": build_private_summary(entries, sessions=sessions) if entries or sessions else empty_summary(),
            "entries": entries,
            "sessions": sessions,
        }
    )
    return templates.TemplateResponse("private_summary.html", context)


@app.get("/public-report", response_class=HTMLResponse)
def public_report(request: Request):
    entries = get_today_logs()
    sessions = get_today_sessions()
    report = build_public_report(entries, sessions=sessions)
    context = build_base_context(request)
    context.update({"report": report, "sessions": sessions})
    return templates.TemplateResponse("public_report.html", context)


@app.get("/artifacts", response_class=HTMLResponse)
def artifacts_page(request: Request):
    entries = get_today_logs()
    sessions = get_today_sessions()
    context = build_base_context(request)
    context.update(
        {
            "artifact_groups": build_artifact_groups(entries),
            "summary": build_private_summary(entries, sessions=sessions) if entries or sessions else empty_summary(),
        }
    )
    return templates.TemplateResponse("artifacts.html", context)


@app.get("/focus", response_class=HTMLResponse)
def focus_mode(request: Request):
    context = build_base_context(request)
    context.update({"summary": get_today_summary()})
    return templates.TemplateResponse("focus.html", context)


@app.post("/tasks")
def create_task(
    h1: str = Form(""),
    h2: str = Form(""),
    h3: str = Form(""),
    h4: str = Form(""),
    h5: str = Form(""),
    note: str = Form(""),
):
    task_service.create_task([h1, h2, h3, h4, h5], note=note)
    return RedirectResponse(url="/tasks", status_code=303)


@app.post("/tasks/{task_id}/update")
def update_task(
    task_id: str,
    h1: str = Form(""),
    h2: str = Form(""),
    h3: str = Form(""),
    h4: str = Form(""),
    h5: str = Form(""),
    note: str = Form(""),
):
    task_service.update_task(task_id, [h1, h2, h3, h4, h5], note=note)
    return RedirectResponse(url="/tasks", status_code=303)


@app.post("/tasks/start")
def start_task(task_id: str = Form(...)):
    task_service.start_task(task_id)
    if not recorder_service.is_running:
        recorder_service.start()
    return RedirectResponse(url="/focus", status_code=303)


@app.post("/tasks/stop")
def stop_task():
    task_service.stop_task()
    return RedirectResponse(url="/", status_code=303)


@app.post("/tasks/capture")
def capture_task_screenshot():
    entry = recorder_service.record_once(capture_kind="manual")
    task_service.attach_screenshot(
        screenshot_path=entry["screenshot_path"],
        captured_at=entry["timestamp"],
        note=entry.get("activity_summary", ""),
    )
    return RedirectResponse(url="/focus", status_code=303)


@app.post("/recording/start")
def start_recording(
    interval_seconds: int = Form(60),
    enable_ocr: bool = Form(False),
    use_ai: bool = Form(False),
    ai_provider: str = Form("mock"),
    ai_threshold: float = Form(0.6),
):
    recorder_service.update_settings(
        interval_seconds=interval_seconds,
        enable_ocr=enable_ocr,
        use_ai=use_ai,
        ai_provider=ai_provider,
        ai_threshold=ai_threshold,
    )
    recorder_service.start()
    return RedirectResponse(url="/", status_code=303)


@app.post("/recording/stop")
def stop_recording():
    recorder_service.stop()
    return RedirectResponse(url="/", status_code=303)


@app.post("/recording/capture")
def capture_once():
    return JSONResponse(recorder_service.record_once())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
