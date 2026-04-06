from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _duration_minutes(entries: list[dict], default_seconds: int = 5) -> tuple[dict[str, float], list[dict]]:
    totals = defaultdict(float)
    enriched: list[dict] = []
    for index, entry in enumerate(entries):
        if index + 1 < len(entries):
            current_ts = _parse_timestamp(entry["timestamp"])
            next_ts = _parse_timestamp(entries[index + 1]["timestamp"])
            seconds = max(default_seconds, min((next_ts - current_ts).total_seconds(), 15 * 60))
        else:
            seconds = default_seconds
        minutes = seconds / 60.0
        label = entry.get("activity_label", "Uncategorized")
        totals[label] += minutes
        item = dict(entry)
        item["duration_minutes"] = round(minutes, 2)
        enriched.append(item)
    return dict(totals), enriched


def _session_task_totals(sessions: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for session in sessions:
        name = session.get("task_path_text") or session.get("task_title") or "Unassigned Task"
        started_at = session.get("started_at", "")
        ended_at = session.get("ended_at", "")
        if started_at and ended_at:
            minutes = max(0.0, (_parse_timestamp(ended_at) - _parse_timestamp(started_at)).total_seconds() / 60.0)
        else:
            minutes = session.get("duration_minutes", 0.0)
        bucket = totals.setdefault(
            name,
            {
                "task_name": name,
                "task_id": session.get("task_id", ""),
                "task_color": session.get("task_color", ""),
                "minutes": 0.0,
            },
        )
        bucket["minutes"] += minutes
        if not bucket["task_color"] and session.get("task_color"):
            bucket["task_color"] = session.get("task_color")
    return [
        {
            "task_name": item["task_name"],
            "task_id": item["task_id"],
            "task_color": item["task_color"],
            "minutes": round(item["minutes"], 1),
        }
        for item in sorted(totals.values(), key=lambda payload: payload["minutes"], reverse=True)
    ]


def _manual_artifact_entries(entries: list[dict]) -> list[dict]:
    return [entry for entry in entries if entry.get("capture_kind") == "manual" and entry.get("screenshot_path")]


def _aggregate_commands(entries: list[dict]) -> tuple[list[dict], int]:
    counts = Counter()
    total = 0
    for entry in entries:
        for item in entry.get("executed_commands", []):
            command = item.get("command", "").strip()
            if not command:
                continue
            counts[command] += 1
            total += 1
    return (
        [{"command": command, "count": count} for command, count in counts.most_common(5)],
        total,
    )


def _aggregate_files(entries: list[dict]) -> tuple[list[dict], list[str], int]:
    counts = Counter()
    directories = Counter()
    for entry in entries:
        for path in entry.get("touched_files", []):
            if path:
                counts[path] += 1
        for path in entry.get("touched_dirs", []):
            if path:
                directories[path] += 1
    top_files = [{"path": path, "count": count} for path, count in counts.most_common(5)]
    top_directories = [path for path, _count in directories.most_common(5)]
    return top_files, top_directories, len(counts)


def _collect_edit_summaries(entries: list[dict]) -> list[str]:
    seen: set[str] = set()
    summaries: list[str] = []
    for entry in entries:
        for summary in entry.get("edit_summaries", []):
            value = summary.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            summaries.append(value)
            if len(summaries) >= 5:
                return summaries
    return summaries


def build_artifact_groups(entries: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for entry in _manual_artifact_entries(entries):
        key = (entry.get("task_id", ""), entry.get("task_started_at", "") or entry.get("task_path_text", ""))
        if key not in grouped:
            grouped[key] = {
                "task_id": entry.get("task_id", ""),
                "task_title": entry.get("task_title", "") or entry.get("activity_label", "Uncategorized"),
                "task_path_text": entry.get("task_path_text", "") or entry.get("task_title", "Unassigned Task"),
                "task_color": entry.get("task_color", ""),
                "started_at": entry.get("task_started_at", "") or entry.get("timestamp", ""),
                "screenshots": [],
            }
        grouped[key]["screenshots"].append(
            {
                "captured_at": entry["timestamp"],
                "screenshot_path": entry["screenshot_path"],
                "note": entry.get("activity_summary", ""),
                "window_title": entry.get("window_title", ""),
            }
        )

    groups = list(grouped.values())
    for group in groups:
        group["screenshots"].sort(key=lambda item: item.get("captured_at", ""))
    groups.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    return groups


def build_private_summary(entries: list[dict], sessions: list[dict] | None = None) -> dict:
    sessions = sessions or []
    totals, timeline = _duration_minutes(entries)
    total_minutes = round(sum(totals.values()), 2)
    top_labels = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)[:3]

    transitions = 0
    transition_hours = Counter()
    previous_label = None
    for entry in entries:
        label = entry.get("activity_label", "")
        if previous_label and previous_label != label:
            transitions += 1
            transition_hours[_parse_timestamp(entry["timestamp"]).strftime("%H:00")] += 1
        previous_label = label

    task_totals = _session_task_totals(sessions)
    artifact_entries = _manual_artifact_entries(entries)
    artifact_count = len(artifact_entries)
    manual_capture_count = artifact_count
    command_totals, command_count = _aggregate_commands(entries)
    top_files, top_directories, edited_file_count = _aggregate_files(entries)
    edit_summaries = _collect_edit_summaries(entries)
    diff_added_lines = sum((entry.get("git_diff_stats", {}) or {}).get("added_lines", 0) for entry in entries)
    diff_removed_lines = sum((entry.get("git_diff_stats", {}) or {}).get("removed_lines", 0) for entry in entries)

    suggestions: list[str] = []
    if not sessions:
        suggestions.append("Start a task before recording to make your log easier to review later.")
    if transitions >= 6:
        suggestions.append("You switched contexts often. Grouping similar work may improve focus.")
    if manual_capture_count == 0 and sessions:
        suggestions.append("Add a manual capture when you finish a meaningful milestone.")
    if command_count == 0:
        suggestions.append("Command capture is empty so shell activity may be under-reported.")
    if edited_file_count == 0 and entries:
        suggestions.append("No saved file changes were detected. Unsaved edits will not appear yet.")
    if not suggestions:
        suggestions.append("Task tracking and activity logging look healthy for this day.")

    return {
        "total_minutes": total_minutes,
        "totals": [{"activity_label": label, "minutes": round(minutes, 1)} for label, minutes in sorted(totals.items(), key=lambda pair: pair[1], reverse=True)],
        "timeline": timeline,
        "top_labels": [{"activity_label": label, "minutes": round(minutes, 1)} for label, minutes in top_labels],
        "long_running": [{"activity_label": label, "minutes": round(minutes, 1)} for label, minutes in sorted(totals.items(), key=lambda pair: pair[1], reverse=True) if minutes >= 10][:5],
        "busy_hours": [{"hour": hour, "count": count} for hour, count in transition_hours.most_common(3)],
        "transition_count": transitions,
        "suggestions": suggestions[:3],
        "task_totals": task_totals[:5],
        "artifact_count": artifact_count,
        "manual_capture_count": manual_capture_count,
        "command_count": command_count,
        "top_commands": command_totals,
        "edited_file_count": edited_file_count,
        "top_files": top_files,
        "top_directories": top_directories,
        "edit_summaries": edit_summaries,
        "diff_stats": {
            "added_lines": diff_added_lines,
            "removed_lines": diff_removed_lines,
        },
    }


def build_public_report(entries: list[dict], sessions: list[dict] | None = None) -> dict:
    sessions = sessions or []
    summary = build_private_summary(entries, sessions=sessions)
    task_names = [item["task_name"] for item in summary["task_totals"][:3]]
    if not task_names:
        task_names = ["No tracked tasks for the selected day."]

    progress = "Tracked work and context switches were summarized from today's activity."
    if summary["task_totals"]:
        progress = f"Primary focus was {summary['task_totals'][0]['task_name']}."
    if summary["edit_summaries"]:
        progress = f"{progress} Recent code changes: {summary['edit_summaries'][0]}"

    tomorrow = "Continue the highest-priority task and capture one milestone artifact."
    if summary["top_files"]:
        tomorrow = f"Continue work around {summary['top_files'][0]['path']} and capture one milestone artifact."
    concerns = "No major blockers were identified from the tracked activity."
    if summary["transition_count"] >= 6:
        concerns = "Frequent context switching may have reduced focus."
    elif summary["command_count"] == 0:
        concerns = "Command history could not be observed, so shell work may be missing."

    artifact_paths = [entry["screenshot_path"] for entry in _manual_artifact_entries(entries)]

    report_lines = ["Today's work"]
    for item in task_names:
        report_lines.append(f"- {item}")
    report_lines.extend(
        [
            "",
            "Progress",
            f"- {progress}",
            "",
            "Next",
            f"- {tomorrow}",
            "",
            "Concerns",
            f"- {concerns}",
            "",
            "Artifacts",
            f"- Manual captures: {summary['manual_capture_count']}",
            f"- Artifact count: {summary['artifact_count']}",
            "",
            "Development signals",
            f"- Commands observed: {summary['command_count']}",
            f"- Files edited: {summary['edited_file_count']}",
        ]
    )
    if summary["top_commands"]:
        report_lines.append(f"- Top command: {summary['top_commands'][0]['command']}")
    if summary["top_files"]:
        report_lines.append(f"- Top file: {summary['top_files'][0]['path']}")
    if summary["edit_summaries"]:
        report_lines.append("- Edit highlights:")
        for item in summary["edit_summaries"][:3]:
            report_lines.append(f"- {item}")
    if summary["top_commands"]:
        report_lines.append("- Commands:")
        for item in summary["top_commands"][:3]:
            report_lines.append(f"- {item['command']} x{item['count']}")
    if summary["top_files"]:
        report_lines.append("- Files:")
        for item in summary["top_files"][:3]:
            report_lines.append(f"- {item['path']} x{item['count']}")

    return {
        "report_items": task_names,
        "progress": progress,
        "tomorrow": tomorrow,
        "concerns": concerns,
        "artifact_count": summary["artifact_count"],
        "manual_capture_count": summary["manual_capture_count"],
        "artifact_paths": artifact_paths,
        "command_count": summary["command_count"],
        "edited_file_count": summary["edited_file_count"],
        "top_commands": summary["top_commands"],
        "top_files": summary["top_files"],
        "top_directories": summary["top_directories"],
        "edit_summaries": summary["edit_summaries"],
        "diff_stats": summary["diff_stats"],
        "report_text": "\n".join(report_lines),
    }
