from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta


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
    totals: dict[str, dict] = {}
    for session in sessions:
        name = session.get("task_path_text") or session.get("task_title") or "未割り当てタスク"
        started_at = session.get("started_at", "")
        ended_at = session.get("ended_at", "")
        if started_at and ended_at:
            minutes = max(0.0, (_parse_timestamp(ended_at) - _parse_timestamp(started_at)).total_seconds() / 60.0)
        else:
            minutes = float(session.get("duration_minutes", 0.0) or 0.0)
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
    return [{"command": command, "count": count} for command, count in counts.most_common(5)], total


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


def _aggregate_remote_sessions(sessions: list[dict]) -> tuple[int, float, list[str]]:
    remote_count = 0
    remote_minutes = 0.0
    hosts = Counter()
    for session in sessions:
        if session.get("work_mode") != "remote":
            continue
        remote_count += 1
        started_at = session.get("started_at", "")
        ended_at = session.get("ended_at", "")
        if started_at and ended_at:
            minutes = max(0.0, (_parse_timestamp(ended_at) - _parse_timestamp(started_at)).total_seconds() / 60.0)
        else:
            minutes = float(session.get("duration_minutes", 0.0) or 0.0)
        remote_minutes += minutes
        host = session.get("remote_host") or session.get("remote_tool") or "リモート接続"
        hosts[host] += 1
    return remote_count, round(remote_minutes, 1), [host for host, _count in hosts.most_common(5)]


def _aggregate_remote_entries(entries: list[dict]) -> tuple[int, float, list[str]]:
    session_ids: set[str] = set()
    hosts = Counter()
    minutes = 0.0
    for entry in entries:
        if entry.get("work_mode") != "remote":
            continue
        session_id = entry.get("remote_session_id") or f"{entry.get('remote_tool', '')}:{entry.get('remote_host', '')}"
        if session_id:
            session_ids.add(session_id)
        host = entry.get("remote_host") or entry.get("remote_tool") or "リモート接続"
        hosts[host] += 1
        minutes += float(entry.get("duration_minutes", 0.0) or 0.0)
    return len(session_ids), round(minutes, 1), [host for host, _count in hosts.most_common(5)]


def _build_private_narrative(summary: dict) -> dict:
    top_task = summary["task_totals"][0]["task_name"] if summary["task_totals"] else "明確な主タスクはありませんでした"
    top_label = summary["top_labels"][0]["activity_label"] if summary["top_labels"] else "活動ラベルは記録されていません"
    task_count = len(summary["task_totals"])
    command_sentence = f"コマンド実行は {summary['command_count']} 件あり" if summary["command_count"] else "コマンド実行は確認されませんでした"
    remote_sentence = (
        f"リモート作業は {summary['remote_session_count']} 回、合計 {summary['remote_minutes']} 分でした。"
        if summary["remote_session_count"]
        else "リモート作業はありませんでした。"
    )
    artifact_sentence = (
        f"手動キャプチャ {summary['manual_capture_count']} 件を含む成果物 {summary['artifact_count']} 件を残しています。"
        if summary["artifact_count"]
        else "成果物として残したキャプチャはありませんでした。"
    )
    overview = (
        f"この日は「{top_task}」を中心に進めました。"
        f"活動ログでは「{top_label}」の比重が高く、総作業時間は {summary['total_minutes']} 分でした。"
    )
    detail = (
        f"記録上は {task_count} 件のタスクに作業が紐づいており、{command_sentence}、"
        f"編集ファイルは {summary['edited_file_count']} 件です。"
        f"{remote_sentence}{artifact_sentence}"
    )
    return {
        "overview": overview,
        "detail": detail,
        "next_action": summary["suggestions"][0] if summary["suggestions"] else "翌日の着手ポイントを1つ決めておくと振り返りやすくなります。",
    }


def _build_public_narrative(summary: dict, task_names: list[str], progress: str, tomorrow: str) -> dict:
    focus_text = "、".join(task_names[:3]) if task_names else "記録された作業項目はありません"
    outline = f"本日は {focus_text} を中心に進めました。総作業時間は {summary['total_minutes']} 分です。"
    support = (
        f"成果物は {summary['artifact_count']} 件で、主なリモート接続先は {', '.join(summary['remote_hosts'][:2])} です。"
        if summary["remote_hosts"]
        else f"成果物は {summary['artifact_count']} 件で、共有に使える記録が残っています。"
    )
    return {
        "outline": outline,
        "progress_paragraph": progress,
        "supporting_note": support,
        "next_action_paragraph": tomorrow,
    }


def build_artifact_groups(entries: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for entry in _manual_artifact_entries(entries):
        key = (entry.get("task_id", ""), entry.get("task_started_at", "") or entry.get("task_path_text", ""))
        if key not in grouped:
            grouped[key] = {
                "task_id": entry.get("task_id", ""),
                "task_title": entry.get("task_title", "") or entry.get("activity_label", "未分類"),
                "task_path_text": entry.get("task_path_text", "") or entry.get("task_title", "未割り当てタスク"),
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
    remote_session_count, remote_minutes, remote_hosts = _aggregate_remote_sessions(sessions)
    if remote_session_count == 0:
        remote_session_count, remote_minutes, remote_hosts = _aggregate_remote_entries(timeline)

    suggestions: list[str] = []
    if not sessions:
        suggestions.append("記録前にタスクを開始しておくと、あとから作業単位で見返しやすくなります。")
    if transitions >= 6:
        suggestions.append("切り替えが多めだったため、翌日は似た作業をまとめると進捗が伝わりやすくなります。")
    if manual_capture_count == 0 and sessions:
        suggestions.append("節目で手動キャプチャを残しておくと、成果物の説明がしやすくなります。")
    if command_count == 0:
        suggestions.append("この時間帯ではコマンド履歴が見つからず、シェル作業が少なめに見えている可能性があります。")
    if edited_file_count == 0 and entries:
        suggestions.append("ローカル編集は検出されませんでした。レビュー中心やリモート支援中心の日なら自然な結果です。")
    if remote_session_count and manual_capture_count == 0:
        suggestions.append("リモート作業中は接続先メモや手動キャプチャを残すと、あとから報告しやすくなります。")
    if not suggestions:
        suggestions.append("この日はタスク記録と作業記録が安定して取得できています。")

    summary = {
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
        "remote_session_count": remote_session_count,
        "remote_minutes": remote_minutes,
        "remote_hosts": remote_hosts,
    }
    summary["narrative"] = _build_private_narrative(summary)
    return summary


def build_public_report(entries: list[dict], sessions: list[dict] | None = None) -> dict:
    sessions = sessions or []
    summary = build_private_summary(entries, sessions=sessions)
    task_names = [item["task_name"] for item in summary["task_totals"][:3]]
    if not task_names:
        task_names = ["この日の作業項目はありません。"]

    progress = "進捗は記録されていますが、タスクの文脈が少ないため、現時点では概要中心の報告としています。"
    if summary["task_totals"]:
        progress = f"主な進捗は {summary['task_totals'][0]['task_name']} を中心に進め、関連する作業を順に整理しました。"
    if summary["edit_summaries"]:
        progress = f"{progress} 代表的な変更として「{summary['edit_summaries'][0]}」を確認しています。"

    tomorrow = "優先度の高い作業を継続し、関係者が状況を追いやすいよう成果物を1つ残す予定です。"
    if summary["top_files"]:
        tomorrow = f"次回は {summary['top_files'][0]['path']} 周辺の作業を継続し、引き継ぎに使える成果物を1つ残す予定です。"

    artifact_paths = [entry["screenshot_path"] for entry in _manual_artifact_entries(entries)]
    narrative = _build_public_narrative(summary, task_names, progress, tomorrow)

    report_lines = [
        "本日の作業報告",
        "",
        f"概要: {narrative['outline']}",
        f"進捗: {narrative['progress_paragraph']}",
        f"補足: {narrative['supporting_note']}",
        f"次のアクション: {narrative['next_action_paragraph']}",
    ]

    return {
        "report_items": task_names,
        "progress": progress,
        "tomorrow": tomorrow,
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
        "remote_session_count": summary["remote_session_count"],
        "remote_minutes": summary["remote_minutes"],
        "remote_hosts": summary["remote_hosts"],
        "narrative": narrative,
        "report_text": "\n".join(report_lines),
    }


def week_start_for(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())


def build_weekly_report(target_date: date, daily_packets: list[dict]) -> dict:
    start_date = week_start_for(target_date)
    end_date = start_date + timedelta(days=6)
    total_minutes = round(sum((packet.get("private_summary", {}) or {}).get("total_minutes", 0) for packet in daily_packets), 1)
    total_artifacts = sum((packet.get("private_summary", {}) or {}).get("artifact_count", 0) for packet in daily_packets)
    total_commands = sum((packet.get("private_summary", {}) or {}).get("command_count", 0) for packet in daily_packets)
    total_remote_minutes = round(sum((packet.get("private_summary", {}) or {}).get("remote_minutes", 0) for packet in daily_packets), 1)

    task_counter = Counter()
    remote_hosts = Counter()
    edit_highlights: list[str] = []
    seen_edits: set[str] = set()
    days: list[dict] = []

    for packet in daily_packets:
        selected_date = packet["date"]
        private_summary = packet["private_summary"]
        public_report = packet["public_report"]
        top_task = private_summary.get("task_totals", [{}])[0] if private_summary.get("task_totals") else {}
        days.append(
            {
                "date_label": selected_date.strftime("%Y-%m-%d"),
                "total_minutes": private_summary.get("total_minutes", 0),
                "top_task_name": top_task.get("task_name", ""),
                "top_task_minutes": top_task.get("minutes", 0),
                "progress": public_report.get("progress", ""),
                "artifact_count": private_summary.get("artifact_count", 0),
                "remote_minutes": private_summary.get("remote_minutes", 0),
                "narrative": public_report.get("narrative", {}).get("outline", ""),
            }
        )
        for item in private_summary.get("task_totals", []):
            task_counter[item.get("task_name", "")] += item.get("minutes", 0)
        for host in private_summary.get("remote_hosts", []):
            remote_hosts[host] += 1
        for summary in private_summary.get("edit_summaries", []):
            if summary and summary not in seen_edits:
                seen_edits.add(summary)
                edit_highlights.append(summary)
            if len(edit_highlights) >= 5:
                break

    key_tasks = [task for task, _count in task_counter.most_common(5) if task]
    overview = (
        f"今週は {', '.join(key_tasks[:3])} を中心に進めました。総作業時間は {total_minutes} 分で、複数日の記録を通じて進捗を積み上げています。"
        if key_tasks
        else f"今週の総作業時間は {total_minutes} 分でした。記録は残っていますが、主タスクは明確に分かれていません。"
    )
    remote_note = (
        f"リモート作業は合計 {total_remote_minutes} 分で、主な接続先は {', '.join(host for host, _ in remote_hosts.most_common(3))} です。"
        if remote_hosts
        else "リモート作業はありませんでした。"
    )
    next_action = (
        f"来週は {key_tasks[0]} を軸に進め、変更点と成果物を早めに揃えて共有できる状態を作ります。"
        if key_tasks
        else "来週は優先度の高い作業を明確にし、日次ごとに成果物を1つ残して振り返りやすい形に整えます。"
    )

    weekly_lines = [
        f"週次報告 ({start_date.isoformat()} - {end_date.isoformat()})",
        "",
        f"総括: {overview}",
        f"補足: {remote_note}",
        f"来週の進め方: {next_action}",
    ]

    return {
        "week_label": f"{start_date.isoformat()} - {end_date.isoformat()}",
        "week_start_iso": start_date.isoformat(),
        "week_end_iso": end_date.isoformat(),
        "total_minutes": total_minutes,
        "artifact_count": total_artifacts,
        "command_count": total_commands,
        "remote_minutes": total_remote_minutes,
        "key_tasks": key_tasks,
        "remote_hosts": [host for host, _count in remote_hosts.most_common(5)],
        "days": days,
        "edit_highlights": edit_highlights[:5],
        "narrative": {
            "overview": overview,
            "remote_note": remote_note,
            "next_action": next_action,
        },
        "report_text": "\n".join(weekly_lines),
    }
