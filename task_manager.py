from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from storage import (
    ACTIVE_TASK_SESSION_PATH,
    TASK_SESSION_LOG_PATH,
    TASKS_PATH,
    append_jsonl,
    read_json,
    write_json,
)


DEFAULT_TASK_COLORS = [
    "#0f766e",
    "#d97706",
    "#2563eb",
    "#b45309",
    "#7c3aed",
    "#be123c",
    "#0891b2",
    "#4d7c0f",
    "#c2410c",
    "#4338ca",
]


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _clean_levels(levels: list[str]) -> list[str]:
    return [level.strip() for level in levels if level and level.strip()]


def _default_color(seed: str) -> str:
    base = seed or "task"
    return DEFAULT_TASK_COLORS[sum(ord(char) for char in base) % len(DEFAULT_TASK_COLORS)]


def _normalize_color(task_id: str, color: str | None) -> str:
    if isinstance(color, str):
        candidate = color.strip()
        if len(candidate) == 7 and candidate.startswith("#"):
            try:
                int(candidate[1:], 16)
                return candidate.lower()
            except ValueError:
                pass
    return _default_color(task_id)


def _task_payload(task_id: str, levels: list[str], note: str, created_at: str, color: str | None = None) -> dict:
    return {
        "id": task_id,
        "levels": levels,
        "title": levels[-1],
        "path_text": " > ".join(levels),
        "note": note.strip(),
        "color": _normalize_color(task_id, color),
        "created_at": created_at,
        "updated_at": _now_iso(),
        "archived": False,
    }


class TaskService:
    def _read_tasks(self) -> list[dict]:
        tasks = read_json(TASKS_PATH, [])
        return tasks if isinstance(tasks, list) else []

    def _write_tasks(self, tasks: list[dict]) -> None:
        write_json(TASKS_PATH, tasks)

    def list_tasks(self) -> list[dict]:
        tasks: list[dict] = []
        for task in self._read_tasks():
            if not isinstance(task, dict) or task.get("archived"):
                continue
            item = dict(task)
            item["color"] = _normalize_color(item.get("id", ""), item.get("color"))
            tasks.append(item)
        return sorted(tasks, key=lambda item: ((item.get("levels") or [""])[0], item.get("levels", []), item.get("created_at", "")))

    def create_task(self, levels: list[str], note: str = "", color: str | None = None) -> dict:
        cleaned_levels = _clean_levels(levels)
        if not cleaned_levels:
            raise ValueError("At least one task level is required.")

        task_id = uuid.uuid4().hex
        task = _task_payload(task_id, cleaned_levels, note, _now_iso(), color=color)
        tasks = self._read_tasks()
        tasks.append(task)
        self._write_tasks(tasks)
        return task

    def update_task(self, task_id: str, levels: list[str], note: str = "", color: str | None = None) -> dict:
        cleaned_levels = _clean_levels(levels)
        if not cleaned_levels:
            raise ValueError("At least one task level is required.")

        tasks = self._read_tasks()
        updated: dict | None = None
        for index, task in enumerate(tasks):
            if task.get("id") != task_id:
                continue
            updated = _task_payload(
                task_id,
                cleaned_levels,
                note,
                task.get("created_at", _now_iso()),
                color=color if color is not None else task.get("color"),
            )
            tasks[index] = updated
            break

        if not updated:
            raise ValueError("Task not found.")

        self._write_tasks(tasks)
        self._sync_active_session(updated)
        return updated

    def get_task(self, task_id: str) -> dict | None:
        for task in self.list_tasks():
            if task.get("id") == task_id:
                return task
        return None

    def get_active_session(self) -> dict | None:
        session = read_json(ACTIVE_TASK_SESSION_PATH, None)
        return session if isinstance(session, dict) and session.get("task_id") else None

    def start_task(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("Selected task was not found.")

        active = self.get_active_session()
        if active and active.get("task_id") == task_id:
            return active
        if active:
            self.stop_task()

        session = {
            "session_id": uuid.uuid4().hex,
            "task_id": task["id"],
            "task_title": task["title"],
            "task_path": task["levels"],
            "task_path_text": task["path_text"],
            "task_color": task.get("color"),
            "started_at": _now_iso(),
            "ended_at": "",
            "screenshots": [],
            "note": task.get("note", ""),
        }
        write_json(ACTIVE_TASK_SESSION_PATH, session)
        return session

    def stop_task(self) -> dict | None:
        active = self.get_active_session()
        if not active:
            return None

        ended_at = _now_iso()
        started_at = datetime.fromisoformat(active["started_at"])
        ended_dt = datetime.fromisoformat(ended_at)
        duration_minutes = round(max(0.0, (ended_dt - started_at).total_seconds() / 60.0), 2)

        completed = {
            **active,
            "ended_at": ended_at,
            "duration_minutes": duration_minutes,
            "artifact_count": len(active.get("screenshots", [])),
        }
        append_jsonl(TASK_SESSION_LOG_PATH, completed)
        write_json(ACTIVE_TASK_SESSION_PATH, {})
        return completed

    def attach_screenshot(self, screenshot_path: str, captured_at: str, note: str = "") -> dict | None:
        active = self.get_active_session()
        if not active:
            return None
        active.setdefault("screenshots", []).append(
            {
                "captured_at": captured_at,
                "screenshot_path": screenshot_path,
                "note": note,
            }
        )
        write_json(ACTIVE_TASK_SESSION_PATH, active)
        return active

    def get_task_context(self) -> dict:
        active = self.get_active_session()
        if not active:
            return {}
        return {
            "task_id": active.get("task_id", ""),
            "task_title": active.get("task_title", ""),
            "task_path": active.get("task_path", []),
            "task_path_text": active.get("task_path_text", ""),
            "task_started_at": active.get("started_at", ""),
            "task_color": active.get("task_color", ""),
        }

    def list_sessions_for_date(self, target_date: date | None = None) -> list[dict]:
        sessions = []
        for item in read_logs_from_jsonl():
            started_at = item.get("started_at", "")
            if target_date and not started_at.startswith(target_date.isoformat()):
                continue
            sessions.append(item)
        active = self.get_active_session()
        if active and (not target_date or active.get("started_at", "").startswith(target_date.isoformat())):
            sessions.append(active)
        sessions.sort(key=lambda item: item.get("started_at", ""))
        return sessions

    def build_task_options(self) -> list[dict]:
        return [
            {
                "id": task["id"],
                "title": task["title"],
                "path_text": task["path_text"],
                "levels": task["levels"],
                "color": task.get("color"),
                "major": (task.get("levels") or ["Uncategorized"])[0],
            }
            for task in self.list_tasks()
        ]

    def build_task_groups(self) -> list[dict]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for task in self.build_task_options():
            grouped[task["major"]].append(task)
        return [{"major": major, "tasks": grouped[major]} for major in sorted(grouped.keys())]

    def get_level_options(self) -> dict[str, list[str]]:
        options: dict[str, set[str]] = {f"h{index}": set() for index in range(1, 6)}
        for task in self.list_tasks():
            for index, level in enumerate(task.get("levels", [])[:5], start=1):
                if level:
                    options[f"h{index}"].add(level)
        return {key: sorted(values) for key, values in options.items()}

    def _sync_active_session(self, task: dict) -> None:
        active = self.get_active_session()
        if not active or active.get("task_id") != task.get("id"):
            return
        active["task_title"] = task["title"]
        active["task_path"] = task["levels"]
        active["task_path_text"] = task["path_text"]
        active["task_color"] = task.get("color")
        active["note"] = task.get("note", "")
        write_json(ACTIVE_TASK_SESSION_PATH, active)


def read_logs_from_jsonl() -> list[dict]:
    return read_jsonl(TASK_SESSION_LOG_PATH)


def read_jsonl(path: Path) -> list[dict]:
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
            except Exception:
                continue
            if isinstance(payload, dict):
                items.append(payload)
    return items
