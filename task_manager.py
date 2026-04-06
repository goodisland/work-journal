from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime

from storage import (
    ACTIVE_TASK_SESSION_PATH,
    TASK_SESSION_LOG_PATH,
    TASKS_PATH,
    append_jsonl,
    read_json,
    write_json,
)


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _clean_levels(levels: list[str]) -> list[str]:
    return [level.strip() for level in levels if level and level.strip()]


def _task_payload(task_id: str, levels: list[str], note: str, created_at: str) -> dict:
    return {
        "id": task_id,
        "levels": levels,
        "title": levels[-1],
        "path_text": " > ".join(levels),
        "note": note.strip(),
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
        tasks = [task for task in self._read_tasks() if isinstance(task, dict) and not task.get("archived")]
        return sorted(tasks, key=lambda item: ((item.get("levels") or [""])[0], item.get("levels", []), item.get("created_at", "")))

    def create_task(self, levels: list[str], note: str = "") -> dict:
        cleaned_levels = _clean_levels(levels)
        if not cleaned_levels:
            raise ValueError("タスク名を最低1つ入力してください。")
        task = _task_payload(uuid.uuid4().hex, cleaned_levels, note, _now_iso())
        tasks = self._read_tasks()
        tasks.append(task)
        self._write_tasks(tasks)
        return task

    def update_task(self, task_id: str, levels: list[str], note: str = "") -> dict:
        cleaned_levels = _clean_levels(levels)
        if not cleaned_levels:
            raise ValueError("タスク名を最低1つ入力してください。")

        tasks = self._read_tasks()
        updated: dict | None = None
        for index, task in enumerate(tasks):
            if task.get("id") != task_id:
                continue
            updated = _task_payload(task_id, cleaned_levels, note, task.get("created_at", _now_iso()))
            tasks[index] = updated
            break

        if not updated:
            raise ValueError("編集対象のタスクが見つかりません。")

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
            raise ValueError("選択されたタスクが見つかりません。")

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
                "major": (task.get("levels") or ["未分類"])[0],
            }
            for task in self.list_tasks()
        ]

    def build_task_groups(self) -> list[dict]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for task in self.build_task_options():
            grouped[task["major"]].append(task)
        return [
            {"major": major, "tasks": grouped[major]}
            for major in sorted(grouped.keys())
        ]

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
        active["note"] = task.get("note", "")
        write_json(ACTIVE_TASK_SESSION_PATH, active)


def read_logs_from_jsonl() -> list[dict]:
    return read_jsonl(TASK_SESSION_LOG_PATH)


def read_jsonl(path) -> list[dict]:
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
