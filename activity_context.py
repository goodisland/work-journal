from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

from storage import ACTIVITY_TRACKER_STATE_PATH, BASE_DIR, COMMAND_LOG_PATH, append_jsonl, read_json, write_json


TRACKED_EXTENSIONS = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
}
IGNORED_DIR_NAMES = {".git", ".idea", ".vscode", "__pycache__", "node_modules"}
IGNORED_PATH_PARTS = {
    ("data", "logs"),
    ("data", "screenshots"),
}
MAX_COMMANDS_PER_CAPTURE = 20
MAX_SUMMARY_ITEMS = 5


def _safe_relpath(path: Path) -> str:
    return str(path.relative_to(BASE_DIR)).replace("\\", "/")


def _normalize_path(value: str, current_cwd: Path) -> Path:
    expanded = os.path.expandvars(value.strip().strip("'\""))
    if not expanded:
        return current_cwd
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = current_cwd / candidate
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def _parse_cd_command(command: str, current_cwd: Path) -> Path:
    command = command.strip()
    match = re.match(r"^(?:Set-Location|cd|chdir)\s+(.+)$", command, re.IGNORECASE)
    if not match:
        return current_cwd
    raw_target = match.group(1).strip()
    if raw_target.startswith("-"):
        return current_cwd
    return _normalize_path(raw_target, current_cwd)


def _powershell_history_path() -> Path | None:
    appdata = os.getenv("APPDATA", "").strip()
    if not appdata:
        return None
    path = Path(appdata) / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt"
    return path if path.exists() else None


def _read_history_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def _summarize_command(command: str) -> str:
    compact = " ".join(command.split())
    if len(compact) <= 120:
        return compact
    return compact[:117] + "..."


def _path_is_ignored(path: Path) -> bool:
    relative_parts = path.relative_to(BASE_DIR).parts
    if any(part in IGNORED_DIR_NAMES for part in relative_parts):
        return True
    if len(relative_parts) >= 2 and tuple(relative_parts[:2]) in IGNORED_PATH_PARTS:
        return True
    return False


def _is_tracked_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if _path_is_ignored(path):
        return False
    if path.suffix.lower() not in TRACKED_EXTENSIONS:
        return False
    try:
        return path.stat().st_size <= 1_000_000
    except OSError:
        return False


def _build_file_snapshot() -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for root, dir_names, file_names in os.walk(BASE_DIR):
        root_path = Path(root)
        dir_names[:] = [name for name in dir_names if name not in IGNORED_DIR_NAMES]
        if root_path != BASE_DIR and _path_is_ignored(root_path):
            dir_names[:] = []
            continue
        for file_name in file_names:
            path = root_path / file_name
            if not _is_tracked_file(path):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[_safe_relpath(path)] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
    return snapshot


def _git_command(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            check=False,
        )
    except Exception:
        return None


def _git_diff_stats(rel_path: str) -> dict:
    diff = _git_command(["diff", "--numstat", "--", rel_path])
    if not diff or diff.returncode not in {0, 1}:
        return {"added": 0, "removed": 0, "tracked": False}
    line = next((item for item in diff.stdout.splitlines() if item.strip()), "")
    if not line:
        status = _git_command(["status", "--short", "--", rel_path])
        is_untracked = bool(status and any(item.startswith("?? ") for item in status.stdout.splitlines()))
        return {"added": 0, "removed": 0, "tracked": not is_untracked}
    parts = line.split("\t")
    if len(parts) < 3:
        return {"added": 0, "removed": 0, "tracked": True}
    return {
        "added": 0 if parts[0] == "-" else int(parts[0]),
        "removed": 0 if parts[1] == "-" else int(parts[1]),
        "tracked": True,
    }


def _git_hunk_headers(rel_path: str) -> list[str]:
    diff = _git_command(["diff", "--unified=0", "--", rel_path])
    if not diff or diff.returncode not in {0, 1}:
        return []
    headers: list[str] = []
    for line in diff.stdout.splitlines():
        if not line.startswith("@@"):
            continue
        if "@@" not in line[2:]:
            continue
        trailing = line.split("@@", 2)[-1].strip()
        if trailing:
            headers.append(trailing)
    return headers[:3]


def _describe_file_change(rel_path: str, previous: dict | None, current: dict | None) -> dict:
    if previous is None and current is not None:
        return {
            "path": rel_path,
            "change_type": "created",
            "directory": str(Path(rel_path).parent).replace("\\", "/") if Path(rel_path).parent != Path(".") else ".",
            "added_lines": 0,
            "removed_lines": 0,
            "summary": f"Created {rel_path}",
            "details": [],
        }
    if previous is not None and current is None:
        return {
            "path": rel_path,
            "change_type": "deleted",
            "directory": str(Path(rel_path).parent).replace("\\", "/") if Path(rel_path).parent != Path(".") else ".",
            "added_lines": 0,
            "removed_lines": 0,
            "summary": f"Deleted {rel_path}",
            "details": [],
        }

    stats = _git_diff_stats(rel_path)
    details = _git_hunk_headers(rel_path)
    detail_suffix = f" in {details[0]}" if details else ""
    summary = f"Updated {rel_path}"
    if stats["added"] or stats["removed"]:
        summary = f"Updated {rel_path} (+{stats['added']}/-{stats['removed']}){detail_suffix}"
    elif not stats["tracked"]:
        summary = f"Updated untracked file {rel_path}"

    return {
        "path": rel_path,
        "change_type": "modified",
        "directory": str(Path(rel_path).parent).replace("\\", "/") if Path(rel_path).parent != Path(".") else ".",
        "added_lines": stats["added"],
        "removed_lines": stats["removed"],
        "summary": summary,
        "details": details,
    }


class ActivityContextCollector:
    def __init__(self) -> None:
        self.state_path = ACTIVITY_TRACKER_STATE_PATH
        self.command_log_path = COMMAND_LOG_PATH

    def collect(self, timestamp: datetime) -> dict:
        state = self._load_state()
        file_snapshot = _build_file_snapshot()
        if not state.get("file_snapshot") and not state.get("shell_history_offsets"):
            baseline = self._build_initial_state(file_snapshot)
            write_json(self.state_path, baseline)
            return self._build_summary([], [])

        commands, cwd = self._collect_commands(timestamp, state)
        file_changes = self._collect_file_changes(state.get("file_snapshot", {}), file_snapshot)
        summary = self._build_summary(commands, file_changes)
        next_state = {
            "file_snapshot": file_snapshot,
            "shell_history_offsets": state.get("shell_history_offsets", {}),
            "shell_cwds": state.get("shell_cwds", {}),
        }
        history_path = _powershell_history_path()
        if history_path:
            next_state["shell_history_offsets"][str(history_path)] = self._history_line_count(history_path)
            next_state["shell_cwds"]["powershell"] = str(cwd)
        write_json(self.state_path, next_state)
        return summary

    def _build_initial_state(self, file_snapshot: dict[str, dict]) -> dict:
        state = {
            "file_snapshot": file_snapshot,
            "shell_history_offsets": {},
            "shell_cwds": {"powershell": str(BASE_DIR)},
        }
        history_path = _powershell_history_path()
        if history_path:
            state["shell_history_offsets"][str(history_path)] = self._history_line_count(history_path)
        return state

    def _load_state(self) -> dict:
        default = {"file_snapshot": {}, "shell_history_offsets": {}, "shell_cwds": {}}
        state = read_json(self.state_path, default)
        if not isinstance(state, dict):
            return default
        return {
            "file_snapshot": state.get("file_snapshot", {}) if isinstance(state.get("file_snapshot", {}), dict) else {},
            "shell_history_offsets": state.get("shell_history_offsets", {}) if isinstance(state.get("shell_history_offsets", {}), dict) else {},
            "shell_cwds": state.get("shell_cwds", {}) if isinstance(state.get("shell_cwds", {}), dict) else {},
        }

    def _history_line_count(self, path: Path) -> int:
        return len(_read_history_lines(path))

    def _collect_commands(self, timestamp: datetime, state: dict) -> tuple[list[dict], Path]:
        history_path = _powershell_history_path()
        if not history_path:
            return [], BASE_DIR

        current_cwd = _normalize_path(
            state.get("shell_cwds", {}).get("powershell", str(BASE_DIR)),
            BASE_DIR,
        )
        lines = _read_history_lines(history_path)
        previous_offset = int(state.get("shell_history_offsets", {}).get(str(history_path), 0) or 0)
        if previous_offset > len(lines):
            previous_offset = 0
        new_lines = [line.strip() for line in lines[previous_offset:] if line.strip()]

        commands: list[dict] = []
        for raw_command in new_lines[-MAX_COMMANDS_PER_CAPTURE:]:
            next_cwd = _parse_cd_command(raw_command, current_cwd)
            item = {
                "timestamp": timestamp.isoformat(),
                "shell": "powershell",
                "command": _summarize_command(raw_command),
                "cwd": _safe_relpath(current_cwd) if str(current_cwd).startswith(str(BASE_DIR)) else str(current_cwd),
            }
            commands.append(item)
            append_jsonl(self.command_log_path, item)
            current_cwd = next_cwd

        state.setdefault("shell_history_offsets", {})[str(history_path)] = len(lines)
        state.setdefault("shell_cwds", {})["powershell"] = str(current_cwd)
        return commands, current_cwd

    def _collect_file_changes(self, previous_snapshot: dict, current_snapshot: dict) -> list[dict]:
        touched_paths = sorted(set(previous_snapshot) | set(current_snapshot))
        changes: list[dict] = []
        for rel_path in touched_paths:
            previous = previous_snapshot.get(rel_path)
            current = current_snapshot.get(rel_path)
            if previous == current:
                continue
            changes.append(_describe_file_change(rel_path, previous, current))
        changes.sort(key=lambda item: (item["change_type"] != "modified", item["path"]))
        return changes[:50]

    def _build_summary(self, commands: list[dict], file_changes: list[dict]) -> dict:
        touched_files = [item["path"] for item in file_changes]
        touched_dirs = sorted({item["directory"] for item in file_changes if item["directory"]})
        top_commands = Counter(item["command"].split()[0] if item["command"] else "" for item in commands)
        top_commands_payload = [
            {"command": command, "count": count}
            for command, count in top_commands.most_common(MAX_SUMMARY_ITEMS)
            if command
        ]
        added_lines = sum(item.get("added_lines", 0) for item in file_changes)
        removed_lines = sum(item.get("removed_lines", 0) for item in file_changes)
        edit_summaries = [item["summary"] for item in file_changes[:MAX_SUMMARY_ITEMS]]

        return {
            "executed_commands": commands,
            "command_count": len(commands),
            "top_commands": top_commands_payload,
            "working_directories": sorted({item["cwd"] for item in commands if item.get("cwd")}),
            "touched_files": touched_files,
            "touched_dirs": touched_dirs,
            "edited_files": file_changes,
            "edited_file_count": len(touched_files),
            "edit_summary": " | ".join(edit_summaries[:3]),
            "edit_summaries": edit_summaries,
            "git_diff_stats": {
                "files": len(touched_files),
                "added_lines": added_lines,
                "removed_lines": removed_lines,
            },
        }
