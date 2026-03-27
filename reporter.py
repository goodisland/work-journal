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
        label = entry.get("activity_label", "その他作業")
        totals[label] += minutes
        item = dict(entry)
        item["duration_minutes"] = round(minutes, 2)
        enriched.append(item)
    return dict(totals), enriched


def build_private_summary(entries: list[dict]) -> dict:
    totals, timeline = _duration_minutes(entries)
    total_minutes = round(sum(totals.values()), 2)
    top_labels = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)[:3]

    transitions = 0
    transition_hours = Counter()
    interruption_like = 0
    previous_label = None
    for entry in entries:
        label = entry.get("activity_label", "")
        if previous_label and previous_label != label:
            transitions += 1
            transition_hours[_parse_timestamp(entry["timestamp"]).strftime("%H:00")] += 1
            if label in {"メール対応", "チャット対応"} or previous_label in {"メール対応", "チャット対応"}:
                interruption_like += 1
        previous_label = label

    suggestions: list[str] = []
    if interruption_like >= 3:
        suggestions.append("メールやチャットの割り込みが多い可能性があります。通知確認の時間帯をまとめると集中しやすいかもしれません。")
    if totals.get("ドキュメント確認", 0) + totals.get("コード確認", 0) >= 20:
        suggestions.append("確認系の時間が長めです。手順や参照先をテンプレ化すると次回の調査が短くなるかもしれません。")
    if transitions >= 6:
        suggestions.append("作業切り替えが多めです。まとまった集中時間を確保できると進みやすい可能性があります。")
    if not suggestions:
        suggestions = [
            "大きな偏りは見られませんでした。主要作業を先に固める進め方が続けやすそうです。",
            "公開用日報は抽象度を上げつつ、自分用ログでは詳細を残す運用が相性よさそうです。",
            "低信頼な分類が目立つ場合は、OCRやAI補完を限定的に有効化すると振り返りがしやすくなります。",
        ]

    return {
        "total_minutes": total_minutes,
        "totals": [{"activity_label": label, "minutes": round(minutes, 1)} for label, minutes in sorted(totals.items(), key=lambda pair: pair[1], reverse=True)],
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
    }


PUBLIC_LABEL_MAP = {
    "実装・コード編集": "実装・コード編集を実施",
    "コード確認": "コード確認やレビュー対応を実施",
    "ドキュメント確認": "仕様確認とドキュメント参照を実施",
    "メール対応": "メールで関係者との調整を実施",
    "チャット対応": "チャットで関係者との調整を実施",
    "CLI作業": "開発用のCLI作業を実施",
    "会議・打ち合わせ": "打ち合わせや会議を実施",
    "その他作業": "周辺作業を実施",
}


def build_public_report(entries: list[dict]) -> dict:
    summary = build_private_summary(entries)
    unique_items: list[str] = []
    for item in summary["top_labels"]:
        text = PUBLIC_LABEL_MAP.get(item["activity_label"], "周辺作業を実施")
        if text not in unique_items:
            unique_items.append(text)
    if not unique_items:
        unique_items.append("作業ログの収集と整理を実施")

    progress = "主要な作業カテゴリを継続しつつ、記録ログの蓄積と振り返り材料の整理を進めました。"
    tomorrow = "継続中の主要タスクを進めつつ、必要に応じて確認系作業を整理する予定です。"
    concerns = "現時点では特記事項はありません。"
    if summary["transition_count"] >= 6:
        concerns = "割り込みや作業切り替えが多めだったため、集中時間の確保が課題です。"

    report_lines = ["今日の実施内容:"]
    for item in unique_items[:3]:
        report_lines.append(f"- {item}")
    report_lines.extend(
        [
            "",
            "進捗:",
            f"- {progress}",
            "",
            "明日の予定:",
            f"- {tomorrow}",
            "",
            "課題/相談:",
            f"- {concerns}",
        ]
    )

    return {
        "report_items": unique_items[:3],
        "progress": progress,
        "tomorrow": tomorrow,
        "concerns": concerns,
        "report_text": "\n".join(report_lines),
    }
