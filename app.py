from __future__ import annotations

import calendar
import os
from collections import defaultdict
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
        "command_count": 0,
        "top_commands": [],
        "edited_file_count": 0,
        "top_files": [],
        "top_directories": [],
        "edit_summaries": [],
        "diff_stats": {"added_lines": 0, "removed_lines": 0},
    }


def resolve_selected_date(request: Request) -> date:
    raw_value = request.query_params.get("date", "").strip()
    if raw_value:
        try:
            return date.fromisoformat(raw_value)
        except ValueError:
            pass
    return date.today()


def session_minutes(session: dict) -> float:
    started_at = session.get("started_at", "")
    ended_at = session.get("ended_at", "")
    if started_at and ended_at:
        return round(max(0.0, (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds() / 60.0), 2)
    if started_at:
        return round(max(0.0, (datetime.now().replace(microsecond=0) - datetime.fromisoformat(started_at)).total_seconds() / 60.0), 2)
    return round(float(session.get("duration_minutes", 0.0) or 0.0), 2)


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_task_lookup() -> dict[str, dict]:
    return {task["id"]: task for task in task_service.list_tasks()}


def decorate_session(session: dict, task_lookup: dict[str, dict]) -> dict:
    item = dict(session)
    task = task_lookup.get(item.get("task_id", ""))
    if task and not item.get("task_color"):
        item["task_color"] = task.get("color", "")
    item["task_name"] = item.get("task_title") or item.get("task_path_text") or "Task"
    item["duration_minutes"] = session_minutes(item)
    return item


def decorate_sessions(sessions: list[dict], task_lookup: dict[str, dict]) -> list[dict]:
    return [decorate_session(session, task_lookup) for session in sessions]


def decorate_entries(entries: list[dict], task_lookup: dict[str, dict]) -> list[dict]:
    enriched: list[dict] = []
    for entry in entries:
        item = dict(entry)
        task = task_lookup.get(item.get("task_id", ""))
        if task and not item.get("task_color"):
            item["task_color"] = task.get("color", "")
        enriched.append(item)
    return enriched


def get_logs_for_date(target_date: date, task_lookup: dict[str, dict] | None = None) -> list[dict]:
    lookup = task_lookup or get_task_lookup()
    return decorate_entries(read_logs(target_date=target_date), lookup)


def get_sessions_for_date(target_date: date, task_lookup: dict[str, dict] | None = None) -> list[dict]:
    lookup = task_lookup or get_task_lookup()
    return decorate_sessions(task_service.list_sessions_for_date(target_date=target_date), lookup)


def get_summary_for_date(target_date: date, task_lookup: dict[str, dict] | None = None) -> dict:
    lookup = task_lookup or get_task_lookup()
    entries = get_logs_for_date(target_date, lookup)
    sessions = get_sessions_for_date(target_date, lookup)
    return build_private_summary(entries, sessions=sessions) if entries or sessions else empty_summary()


def available_log_dates() -> list[date]:
    values: set[date] = {date.today()}
    for entry in read_logs(target_date=None):
        timestamp = entry.get("timestamp", "")
        if len(timestamp) >= 10:
            try:
                values.add(date.fromisoformat(timestamp[:10]))
            except ValueError:
                pass
    for session in task_service.list_sessions_for_date(target_date=None):
        started_at = session.get("started_at", "")
        if len(started_at) >= 10:
            try:
                values.add(date.fromisoformat(started_at[:10]))
            except ValueError:
                pass
    return sorted(values)


def build_date_browser(selected_date: date) -> dict:
    dates = available_log_dates()
    selected_iso = selected_date.isoformat()
    chip_dates = dates[-12:]
    if selected_date not in chip_dates:
        chip_dates = sorted((chip_dates + [selected_date]))[-12:]
    latest_dates = list(reversed(chip_dates))
    current_index = dates.index(selected_date) if selected_date in dates else None
    previous_date = dates[current_index - 1] if current_index and current_index > 0 else None
    next_date = dates[current_index + 1] if current_index is not None and current_index + 1 < len(dates) else None
    return {
        "selected_date_iso": selected_iso,
        "selected_date_label": selected_date.strftime("%Y-%m-%d"),
        "available_dates": [
            {
                "iso": item.isoformat(),
                "label": item.strftime("%m/%d"),
                "is_selected": item == selected_date,
            }
            for item in latest_dates
        ],
        "previous_date_iso": previous_date.isoformat() if previous_date else "",
        "next_date_iso": next_date.isoformat() if next_date else "",
    }


def month_start(value: date) -> date:
    return value.replace(day=1)


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def build_calendar_view(selected_date: date, task_lookup: dict[str, dict]) -> dict:
    calendar_month = month_start(selected_date)
    month_sessions = decorate_sessions(task_service.list_sessions_for_date(target_date=None), task_lookup)
    day_totals: dict[str, dict] = defaultdict(lambda: {"total_minutes": 0.0, "tasks": defaultdict(lambda: {"minutes": 0.0, "color": "", "name": ""})})

    for session in month_sessions:
        started_at = session.get("started_at", "")
        if len(started_at) < 10:
            continue
        day_iso = started_at[:10]
        minutes = session_minutes(session)
        bucket = day_totals[day_iso]
        bucket["total_minutes"] += minutes
        task_name = session.get("task_title") or session.get("task_path_text") or "Task"
        task_bucket = bucket["tasks"][task_name]
        task_bucket["minutes"] += minutes
        task_bucket["color"] = session.get("task_color") or task_bucket["color"] or "#94a3b8"
        task_bucket["name"] = task_name

    month_keys = [day_iso for day_iso in day_totals.keys() if day_iso.startswith(calendar_month.strftime("%Y-%m"))]
    month_max = max((day_totals[day_iso]["total_minutes"] for day_iso in month_keys), default=0.0)
    month_total_minutes = round(sum(day_totals[day_iso]["total_minutes"] for day_iso in month_keys), 1)

    weeks: list[list[dict]] = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(calendar_month.year, calendar_month.month):
        week_cells: list[dict] = []
        for day_value in week:
            day_iso = day_value.isoformat()
            payload = day_totals.get(day_iso, {"total_minutes": 0.0, "tasks": {}})
            task_rows = sorted(payload["tasks"].values(), key=lambda item: item["minutes"], reverse=True)
            total_minutes = round(payload["total_minutes"], 1)
            segments = [
                {
                    "task_name": item["name"],
                    "task_color": item["color"],
                    "minutes": round(item["minutes"], 1),
                    "width": round((item["minutes"] / payload["total_minutes"]) * 100, 1) if payload["total_minutes"] else 0.0,
                }
                for item in task_rows[:3]
            ]
            events = [
                {
                    "task_name": item["name"],
                    "task_color": item["color"],
                    "minutes": round(item["minutes"], 1),
                }
                for item in task_rows[:3]
            ]
            week_cells.append(
                {
                    "date_iso": day_iso,
                    "day_number": day_value.day,
                    "is_current_month": day_value.month == calendar_month.month,
                    "is_selected": day_value == selected_date,
                    "is_today": day_value == date.today(),
                    "total_minutes": total_minutes,
                    "intensity": round(payload["total_minutes"] / month_max, 3) if month_max else 0.0,
                    "top_task_name": task_rows[0]["name"] if task_rows else "",
                    "events": events,
                    "segments": segments,
                }
            )
        weeks.append(week_cells)

    task_legend = []
    monthly_task_totals: dict[str, dict] = {}
    for day_iso in month_keys:
        for task_item in day_totals[day_iso]["tasks"].values():
            bucket = monthly_task_totals.setdefault(
                task_item["name"],
                {
                    "task_name": task_item["name"],
                    "task_color": task_item["color"],
                    "minutes": 0.0,
                },
            )
            bucket["minutes"] += task_item["minutes"]
    for item in sorted(monthly_task_totals.values(), key=lambda payload: payload["minutes"], reverse=True)[:5]:
        task_legend.append(
            {
                "task_name": item["task_name"],
                "task_color": item["task_color"],
                "minutes": round(item["minutes"], 1),
            }
        )

    return {
        "month_label": calendar_month.strftime("%Y-%m"),
        "month_anchor_iso": calendar_month.isoformat(),
        "previous_month_iso": previous_month(calendar_month).isoformat(),
        "next_month_iso": next_month(calendar_month).isoformat(),
        "weeks": weeks,
        "legend": task_legend,
        "month_total_minutes": month_total_minutes,
    }


def build_day_schedule(selected_date: date, sessions: list[dict]) -> dict:
    day_start = datetime.combine(selected_date, datetime.min.time())
    day_end = day_start.replace(hour=23, minute=59, second=59)
    schedule_rows = []

    for hour in range(24):
        slot_start = day_start.replace(hour=hour)
        slot_end = slot_start.replace(minute=59, second=59)
        items = []
        for session in sessions:
            started_at = parse_dt(session.get("started_at", ""))
            ended_at = parse_dt(session.get("ended_at", "")) or datetime.now().replace(microsecond=0)
            if not started_at:
                continue
            clipped_start = max(started_at, slot_start)
            clipped_end = min(ended_at, slot_end)
            if clipped_end <= clipped_start:
                continue
            minutes = round((clipped_end - clipped_start).total_seconds() / 60.0, 1)
            items.append(
                {
                    "task_name": session.get("task_title") or session.get("task_path_text") or "Task",
                    "task_path_text": session.get("task_path_text", ""),
                    "task_color": session.get("task_color") or "#94a3b8",
                    "start_label": clipped_start.strftime("%H:%M"),
                    "end_label": clipped_end.strftime("%H:%M"),
                    "minutes": minutes,
                }
            )
        schedule_rows.append(
            {
                "hour_label": f"{hour:02d}:00",
                "entries": items,
            }
        )

    day_total_minutes = round(sum(session_minutes(session) for session in sessions), 1)
    return {
        "selected_date_label": selected_date.strftime("%Y-%m-%d"),
        "day_total_minutes": day_total_minutes,
        "rows": schedule_rows,
    }


def build_base_context(request: Request, selected_date: date | None = None, show_log_filters: bool = False) -> dict:
    target_date = selected_date or resolve_selected_date(request)
    task_lookup = get_task_lookup()
    active_session = task_service.get_active_session()
    active_session = decorate_session(active_session, task_lookup) if active_session else None
    selected_sessions = get_sessions_for_date(target_date, task_lookup)
    return {
        "request": request,
        "recording": recorder_service.is_running,
        "recorder_settings": {
            "interval_seconds": recorder_service.interval_seconds,
            "enable_ocr": recorder_service.enable_ocr,
            "use_ai": recorder_service.use_ai,
            "ai_provider": recorder_service.ai_provider,
            "ai_threshold": recorder_service.ai_threshold,
        },
        "active_session": active_session,
        "task_options": task_service.build_task_options(),
        "task_groups": task_service.build_task_groups(),
        "now_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today_iso": date.today().isoformat(),
        "current_path": request.url.path,
        "current_url": str(request.url),
        "ui_state": {
            "recording": recorder_service.is_running,
            "active_task_id": active_session.get("task_id", "") if active_session else "",
            "active_session_started_at": active_session.get("started_at", "") if active_session else "",
        },
        "selected_date": target_date,
        "show_log_filters": show_log_filters,
        "date_browser": build_date_browser(target_date),
        "calendar_view": build_calendar_view(target_date, task_lookup),
        "day_schedule": build_day_schedule(target_date, selected_sessions),
        "task_lookup": task_lookup,
    }


@app.get("/api/ui-state")
def ui_state():
    active_session = task_service.get_active_session()
    return JSONResponse(
        {
            "recording": recorder_service.is_running,
            "active_task_id": active_session.get("task_id", "") if active_session else "",
            "active_session_started_at": active_session.get("started_at", "") if active_session else "",
        }
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    selected_date = resolve_selected_date(request)
    task_lookup = get_task_lookup()
    entries = get_logs_for_date(selected_date, task_lookup)
    sessions = get_sessions_for_date(selected_date, task_lookup)
    context = build_base_context(request, selected_date=selected_date, show_log_filters=True)
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


@app.get("/calendar-day", response_class=HTMLResponse)
def calendar_day_detail(request: Request):
    selected_date = resolve_selected_date(request)
    task_lookup = get_task_lookup()
    sessions = get_sessions_for_date(selected_date, task_lookup)
    context = build_base_context(request, selected_date=selected_date)
    context.update(
        {
            "title": f"{selected_date.isoformat()} details",
            "sessions": sessions,
            "summary": get_summary_for_date(selected_date, task_lookup),
        }
    )
    return templates.TemplateResponse("calendar_day_detail.html", context)


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    context = build_base_context(request)
    context.update({"level_options": task_service.get_level_options(), "editing_task": None})
    return templates.TemplateResponse("tasks.html", context)


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_page(request: Request, task_id: str):
    context = build_base_context(request)
    context.update({"level_options": task_service.get_level_options(), "editing_task": task_service.get_task(task_id)})
    return templates.TemplateResponse("tasks.html", context)


@app.get("/timeline", response_class=HTMLResponse)
def timeline(request: Request):
    selected_date = resolve_selected_date(request)
    entries = list(reversed(get_logs_for_date(selected_date)))
    context = build_base_context(request, selected_date=selected_date, show_log_filters=True)
    context.update({"entries": entries})
    return templates.TemplateResponse("timeline.html", context)


@app.get("/private-summary", response_class=HTMLResponse)
def private_summary(request: Request):
    selected_date = resolve_selected_date(request)
    task_lookup = get_task_lookup()
    entries = get_logs_for_date(selected_date, task_lookup)
    sessions = get_sessions_for_date(selected_date, task_lookup)
    context = build_base_context(request, selected_date=selected_date, show_log_filters=True)
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
    selected_date = resolve_selected_date(request)
    task_lookup = get_task_lookup()
    entries = get_logs_for_date(selected_date, task_lookup)
    sessions = get_sessions_for_date(selected_date, task_lookup)
    report = build_public_report(entries, sessions=sessions)
    context = build_base_context(request, selected_date=selected_date, show_log_filters=True)
    context.update({"report": report, "sessions": sessions})
    return templates.TemplateResponse("public_report.html", context)


@app.get("/artifacts", response_class=HTMLResponse)
def artifacts_page(request: Request):
    selected_date = resolve_selected_date(request)
    task_lookup = get_task_lookup()
    entries = get_logs_for_date(selected_date, task_lookup)
    sessions = get_sessions_for_date(selected_date, task_lookup)
    context = build_base_context(request, selected_date=selected_date, show_log_filters=True)
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
    context.update({"summary": get_summary_for_date(date.today(), context["task_lookup"])})
    return templates.TemplateResponse("focus.html", context)


@app.get("/mini-control", response_class=HTMLResponse)
def mini_control(request: Request):
    context = build_base_context(request)
    context.update({"summary": get_summary_for_date(date.today(), context["task_lookup"])})
    return templates.TemplateResponse("mini_control.html", context)


@app.post("/tasks")
def create_task(
    h1: str = Form(""),
    h2: str = Form(""),
    h3: str = Form(""),
    h4: str = Form(""),
    h5: str = Form(""),
    note: str = Form(""),
    color: str = Form("#0f766e"),
):
    task_service.create_task([h1, h2, h3, h4, h5], note=note, color=color)
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
    color: str = Form("#0f766e"),
):
    task_service.update_task(task_id, [h1, h2, h3, h4, h5], note=note, color=color)
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
    redirect_to: str = Form("/"),
):
    recorder_service.update_settings(
        interval_seconds=interval_seconds,
        enable_ocr=enable_ocr,
        use_ai=use_ai,
        ai_provider=ai_provider,
        ai_threshold=ai_threshold,
    )
    recorder_service.start()
    if not redirect_to or not redirect_to.startswith("/"):
        redirect_to = "/"
    return RedirectResponse(url=redirect_to, status_code=303)


@app.post("/recording/stop")
def stop_recording(redirect_to: str = Form("/")):
    recorder_service.stop()
    task_service.stop_task()
    if not redirect_to or not redirect_to.startswith("/"):
        redirect_to = "/"
    return RedirectResponse(url=redirect_to, status_code=303)


@app.post("/recording/pause")
def pause_recording(redirect_to: str = Form("/")):
    recorder_service.stop()
    if not redirect_to or not redirect_to.startswith("/"):
        redirect_to = "/"
    return RedirectResponse(url=redirect_to, status_code=303)


@app.post("/recording/capture")
def capture_once():
    return JSONResponse(recorder_service.record_once())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
