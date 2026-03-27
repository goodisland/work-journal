from __future__ import annotations

import os
from datetime import date

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from recorder import RecorderService
from reporter import build_private_summary, build_public_report
from sample_data import ensure_sample_data
from storage import BASE_DIR, ensure_directories, read_logs


load_dotenv(override=True)
ensure_directories()
ensure_sample_data()

app = FastAPI(title="Work Journal Mock")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/data", StaticFiles(directory=str(BASE_DIR / "data")), name="data")

recorder_service = RecorderService(
    interval_seconds=int(os.getenv("CAPTURE_INTERVAL_SECONDS", "60")),
    enable_ocr=os.getenv("OCR_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
    use_ai=os.getenv("AI_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
    ai_provider=os.getenv("AI_PROVIDER", "mock"),
    ai_threshold=float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.6")),
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
    }


def get_today_logs() -> list[dict]:
    return read_logs(target_date=date.today())


def get_today_summary() -> dict:
    entries = get_today_logs()
    return build_private_summary(entries) if entries else empty_summary()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    entries = get_today_logs()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "recording": recorder_service.is_running,
            "entries": entries,
            "summary": build_private_summary(entries) if entries else empty_summary(),
            "settings": {
                "interval_seconds": recorder_service.interval_seconds,
                "enable_ocr": recorder_service.enable_ocr,
                "use_ai": recorder_service.use_ai,
                "ai_provider": recorder_service.ai_provider,
                "ai_threshold": recorder_service.ai_threshold,
            },
        },
    )


@app.get("/timeline", response_class=HTMLResponse)
def timeline(request: Request):
    entries = list(reversed(get_today_logs()))
    return templates.TemplateResponse(
        "timeline.html",
        {"request": request, "entries": entries, "recording": recorder_service.is_running},
    )


@app.get("/private-summary", response_class=HTMLResponse)
def private_summary(request: Request):
    entries = get_today_logs()
    summary = build_private_summary(entries) if entries else empty_summary()
    return templates.TemplateResponse(
        "private_summary.html",
        {"request": request, "summary": summary, "entries": entries},
    )


@app.get("/public-report", response_class=HTMLResponse)
def public_report(request: Request):
    entries = get_today_logs()
    report = build_public_report(entries) if entries else build_public_report([])
    return templates.TemplateResponse(
        "public_report.html",
        {"request": request, "report": report},
    )


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
