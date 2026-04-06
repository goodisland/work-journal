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
        label = entry.get("activity_label", "未分類")
        totals[label] += minutes
        item = dict(entry)
        item["duration_minutes"] = round(minutes, 2)
        enriched.append(item)
    return dict(totals), enriched


def _session_task_totals(sessions: list[dict]) -> list[dict]:
    totals = defaultdict(float)
    for session in sessions:
        name = session.get("task_path_text") or session.get("task_title") or "未設定タスク"
        started_at = session.get("started_at", "")
        ended_at = session.get("ended_at", "")
        if started_at and ended_at:
            minutes = max(0.0, (_parse_timestamp(ended_at) - _parse_timestamp(started_at)).total_seconds() / 60.0)
        else:
            minutes = session.get("duration_minutes", 0.0)
        totals[name] += minutes
    return [
        {"task_name": name, "minutes": round(minutes, 1)}
        for name, minutes in sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
    ]


def _manual_artifact_entries(entries: list[dict]) -> list[dict]:
    return [
        entry for entry in entries
        if entry.get("capture_kind") == "manual" and entry.get("screenshot_path")
    ]


def build_artifact_groups(entries: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for entry in _manual_artifact_entries(entries):
        key = (
            entry.get("task_id", ""),
            entry.get("task_started_at", "") or entry.get("task_path_text", ""),
        )
        if key not in grouped:
            grouped[key] = {
                "task_id": entry.get("task_id", ""),
                "task_title": entry.get("task_title", "") or entry.get("activity_label", "未分類"),
                "task_path_text": entry.get("task_path_text", "") or entry.get("task_title", "未設定タスク"),
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

    suggestions: list[str] = []
    if not sessions:
        suggestions.append("タスクを開始すると、開始時刻・終了時刻・成果物スクリーンショットをまとめて追跡できます。")
    if transitions >= 6:
        suggestions.append("作業切り替えが多めです。大項目単位でまとまった時間を確保すると記録が見やすくなります。")
    if manual_capture_count == 0 and sessions:
        suggestions.append("成果物を残したい場面で手動スクリーンショットを押すと、報告に添付しやすくなります。")
    if not suggestions:
        suggestions.append("タスク定義と実作業ログがそろっていて、振り返りに使いやすい状態です。")

    return {
        "total_minutes": total_minutes,
        "totals": [
            {"activity_label": label, "minutes": round(minutes, 1)}
            for label, minutes in sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
        ],
        "timeline": timeline,
        "top_labels": [{"activity_label": label, "minutes": round(minutes, 1)} for label, minutes in top_labels],
        "long_running": [
            {"activity_label": label, "minutes": round(minutes, 1)}
            for label, minutes in sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
            if minutes >= 10
        ][:5],
        "busy_hours": [{"hour": hour, "count": count} for hour, count in transition_hours.most_common(3)],
        "transition_count": transitions,
        "suggestions": suggestions[:3],
        "task_totals": task_totals[:5],
        "artifact_count": artifact_count,
        "manual_capture_count": manual_capture_count,
    }


def build_public_report(entries: list[dict], sessions: list[dict] | None = None) -> dict:
    sessions = sessions or []
    summary = build_private_summary(entries, sessions=sessions)
    task_names = [item["task_name"] for item in summary["task_totals"][:3]]
    if not task_names:
        task_names = ["本日の明示的なタスク着手はありませんでした。"]

    progress = "開始時刻と終了時刻を含むセッション単位で、本日の作業を記録しました。"
    if summary["task_totals"]:
        progress = f"主要タスクは {summary['task_totals'][0]['task_name']} を中心に進行しました。"

    tomorrow = "同じ階層タスクを継続する場合は、そのまま再開して作業の連続性を残せます。"
    concerns = "大きな阻害要因は記録されていません。"
    if summary["transition_count"] >= 6:
        concerns = "短時間での切り替えが多く、集中時間が分散している可能性があります。"

    artifact_paths = [entry["screenshot_path"] for entry in _manual_artifact_entries(entries)]

    report_lines = ["本日の報告:"]
    for item in task_names:
        report_lines.append(f"- {item}")
    report_lines.extend(
        [
            "",
            "進捗",
            f"- {progress}",
            "",
            "明日の予定",
            f"- {tomorrow}",
            "",
            "懸念事項",
            f"- {concerns}",
            "",
            "成果物",
            f"- 手動キャプチャ数: {summary['manual_capture_count']}",
            f"- 添付候補数: {summary['artifact_count']}",
        ]
    )

    return {
        "report_items": task_names,
        "progress": progress,
        "tomorrow": tomorrow,
        "concerns": concerns,
        "artifact_count": summary["artifact_count"],
        "manual_capture_count": summary["manual_capture_count"],
        "artifact_paths": artifact_paths,
        "report_text": "\n".join(report_lines),
    }
