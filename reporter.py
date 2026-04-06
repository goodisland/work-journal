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
        suggestions.append("記録を始める前にタスクを開始しておくと、あとからログを見返しやすくなります。")
    if transitions >= 6:
        suggestions.append("作業の切り替えが多めでした。似た作業をまとめると集中しやすくなるかもしれません。")
    if manual_capture_count == 0 and sessions:
        suggestions.append("区切りのよいタイミングで手動キャプチャを残すと、進捗を追いやすくなります。")
    if command_count == 0:
        suggestions.append("コマンド記録が空なので、シェル作業が十分に反映されていない可能性があります。")
    if edited_file_count == 0 and entries:
        suggestions.append("保存されたファイル変更は検出されませんでした。未保存の編集はまだ反映されません。")
    if not suggestions:
        suggestions.append("この日はタスク記録とアクティビティ記録が安定して取れています。")

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
        task_names = ["選択日の記録タスクはありません。"]

    progress = "この日の作業内容と切り替え状況をもとに進捗をまとめました。"
    if summary["task_totals"]:
        progress = f"主な作業対象は {summary['task_totals'][0]['task_name']} でした。"
    if summary["edit_summaries"]:
        progress = f"{progress} 直近の変更内容: {summary['edit_summaries'][0]}"

    tomorrow = "優先度の高いタスクを継続し、節目で成果物を1件残してください。"
    if summary["top_files"]:
        tomorrow = f"{summary['top_files'][0]['path']} 周辺の作業を継続し、節目で成果物を1件残してください。"
    concerns = "記録されたアクティビティからは大きな懸念は見つかりませんでした。"
    if summary["transition_count"] >= 6:
        concerns = "作業の切り替えが多く、集中が分散していた可能性があります。"
    elif summary["command_count"] == 0:
        concerns = "コマンド履歴を確認できなかったため、シェル作業が十分に反映されていない可能性があります。"

    artifact_paths = [entry["screenshot_path"] for entry in _manual_artifact_entries(entries)]

    report_lines = ["本日の作業"]
    for item in task_names:
        report_lines.append(f"- {item}")
    report_lines.extend(
        [
            "",
            "進捗",
            f"- {progress}",
            "",
            "次のアクション",
            f"- {tomorrow}",
            "",
            "懸念点",
            f"- {concerns}",
            "",
            "成果物",
            f"- 手動キャプチャ: {summary['manual_capture_count']}",
            f"- 成果物数: {summary['artifact_count']}",
            "",
            "開発シグナル",
            f"- コマンド数: {summary['command_count']}",
            f"- 編集ファイル数: {summary['edited_file_count']}",
        ]
    )
    if summary["top_commands"]:
        report_lines.append(f"- 最多コマンド: {summary['top_commands'][0]['command']}")
    if summary["top_files"]:
        report_lines.append(f"- 主なファイル: {summary['top_files'][0]['path']}")
    if summary["edit_summaries"]:
        report_lines.append("- 編集ハイライト:")
        for item in summary["edit_summaries"][:3]:
            report_lines.append(f"- {item}")
    if summary["top_commands"]:
        report_lines.append("- コマンド一覧:")
        for item in summary["top_commands"][:3]:
            report_lines.append(f"- {item['command']} x{item['count']}")
    if summary["top_files"]:
        report_lines.append("- ファイル一覧:")
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
