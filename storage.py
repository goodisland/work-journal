from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
LOGS_DIR = DATA_DIR / "logs"
REPORTS_DIR = DATA_DIR / "reports"
ACTIVITY_LOG_PATH = LOGS_DIR / "activity_log.jsonl"
SAMPLE_LOG_PATH = LOGS_DIR / "sample_activity_log.jsonl"
COMMAND_LOG_PATH = LOGS_DIR / "command_log.jsonl"
TASKS_PATH = DATA_DIR / "tasks.json"
ACTIVE_TASK_SESSION_PATH = DATA_DIR / "active_task_session.json"
ACTIVE_REMOTE_SESSION_PATH = DATA_DIR / "active_remote_session.json"
TASK_SESSION_LOG_PATH = LOGS_DIR / "task_sessions.jsonl"
ACTIVITY_TRACKER_STATE_PATH = DATA_DIR / "activity_tracker_state.json"


def ensure_directories() -> None:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def get_screenshot_path(ts: datetime) -> Path:
    daily_dir = SCREENSHOTS_DIR / ts.strftime("%Y-%m-%d")
    daily_dir.mkdir(parents=True, exist_ok=True)
    return daily_dir / f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}.png"


def get_daily_report_dir(target_date: date) -> Path:
    report_dir = REPORTS_DIR / target_date.isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def get_weekly_report_dir(week_start: date) -> Path:
    report_dir = REPORTS_DIR / f"week-{week_start.isoformat()}"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def append_log(entry: dict) -> None:
    ensure_directories()
    with ACTIVITY_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, entry: dict) -> None:
    ensure_directories()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_log_file(path: Path, entries: Iterable[dict]) -> None:
    ensure_directories()
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_json(path: Path, default):
    ensure_directories()
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: object) -> None:
    ensure_directories()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    ensure_directories()
    if not path.exists():
        return []
    items: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                items.append(payload)
    return items


def read_logs(target_date: date | None = None, include_sample: bool = True) -> list[dict]:
    ensure_directories()
    entries: list[dict] = []
    for path in _candidate_log_files(include_sample=include_sample):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if target_date and not item.get("timestamp", "").startswith(target_date.isoformat()):
                    continue
                entries.append(item)
    entries.sort(key=lambda item: item.get("timestamp", ""))
    return entries


def _candidate_log_files(include_sample: bool = True) -> list[Path]:
    paths = [ACTIVITY_LOG_PATH]
    if include_sample:
        paths.append(SAMPLE_LOG_PATH)
    return paths


def detect_jsonl_kind(entries: list[dict]) -> str:
    if any("timestamp" in entry for entry in entries):
        return "activity"
    if any("session_id" in entry or "started_at" in entry for entry in entries):
        return "task_sessions"
    return "unknown"


def _activity_entry_key(entry: dict) -> tuple:
    return (
        entry.get("timestamp", ""),
        entry.get("capture_kind", ""),
        entry.get("screenshot_path", ""),
        entry.get("task_id", ""),
        entry.get("remote_tool", ""),
        entry.get("remote_host", ""),
    )


def _task_session_key(entry: dict) -> tuple:
    session_id = entry.get("session_id", "")
    if session_id:
        return ("session_id", session_id)
    return (
        "session_fallback",
        entry.get("started_at", ""),
        entry.get("ended_at", ""),
        entry.get("task_id", ""),
        entry.get("remote_tool", ""),
        entry.get("remote_host", ""),
    )


def import_jsonl_entries(path: Path, entries: list[dict], kind: str) -> dict:
    ensure_directories()
    if kind == "activity":
        key_fn = _activity_entry_key
    elif kind == "task_sessions":
        key_fn = _task_session_key
    else:
        raise ValueError("Unsupported import kind.")

    existing_entries = read_jsonl(path)
    known_keys = {key_fn(entry) for entry in existing_entries}
    imported = 0
    skipped = 0

    for entry in entries:
        key = key_fn(entry)
        if key in known_keys:
            skipped += 1
            continue
        append_jsonl(path, entry)
        known_keys.add(key)
        imported += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(entries),
        "kind": kind,
        "path": str(path),
    }
