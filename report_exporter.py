from __future__ import annotations

import re
from pathlib import Path


def _strip_html(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text


def save_html(path: Path, html: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def _build_pdf_story(title: str, export_name: str, payload: dict):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.pdfmetrics import registerFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    styles = getSampleStyleSheet()
    base_font = "HeiseiKakuGo-W5"
    styles.add(
        ParagraphStyle(
            name="ReportBody",
            parent=styles["BodyText"],
            fontName=base_font,
            fontSize=10.5,
            leading=16,
            alignment=TA_LEFT,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName=base_font,
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#17212b"),
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportHeading",
            parent=styles["Heading2"],
            fontName=base_font,
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#0f766e"),
            spaceBefore=8,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSmall",
            parent=styles["BodyText"],
            fontName=base_font,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#55626f"),
        )
    )

    def p(text: str, style: str = "ReportBody"):
        escaped = (
            str(text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        return Paragraph(escaped, styles[style])

    def add_kv_table(rows: list[list[str]], col_widths=None):
        table = Table(rows, colWidths=col_widths, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), base_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                    ("LEADING", (0, 0), (-1, -1), 13),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f7f9")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#17212b")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e2e8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    story = [p(title, "ReportTitle")]

    if export_name == "private_summary":
        summary = payload["summary"]
        sessions = payload.get("sessions", [])
        meta_rows = [
            ["総作業時間", f"{summary['total_minutes']} min", "成果物数", str(summary["artifact_count"])],
            ["コマンド数", str(summary["command_count"]), "リモート時間", f"{summary['remote_minutes']} min"],
        ]
        story.extend([add_kv_table(meta_rows, [32 * mm, 38 * mm, 32 * mm, 38 * mm]), Spacer(1, 10)])

        story.append(p("1. 本日の要約", "ReportHeading"))
        story.append(p(summary["narrative"]["overview"]))
        story.append(p(summary["narrative"]["detail"]))
        story.append(p(f"次の着眼点: {summary['narrative']['next_action']}"))

        story.append(p("2. タスク別実績", "ReportHeading"))
        task_rows = [["タスク", "時間"]] + [[item["task_name"], f"{item['minutes']} min"] for item in summary["task_totals"]]
        if len(task_rows) == 1:
            task_rows.append(["記録なし", "-"])
        story.extend([add_kv_table(task_rows, [120 * mm, 35 * mm]), Spacer(1, 8)])

        story.append(p("3. 編集・コマンドのハイライト", "ReportHeading"))
        edit_lines = summary["edit_summaries"] or ["編集ハイライトはありません。"]
        command_lines = [f"{item['command']} ({item['count']}回)" for item in summary["top_commands"]] or ["コマンド記録はありません。"]
        for line in edit_lines:
            story.append(p(f"・{line}"))
        story.append(Spacer(1, 4))
        for line in command_lines:
            story.append(p(f"・{line}"))

        story.append(p("4. セッション一覧", "ReportHeading"))
        session_rows = [["時間帯", "内容"]]
        for session in sessions:
            detail = session.get("task_path_text", "")
            if session.get("work_mode") == "remote":
                remote_tool = session.get("remote_tool") or "リモート接続"
                remote_host = session.get("remote_host", "")
                detail = f"{detail}\nリモート: {remote_tool}" + (f" / {remote_host}" if remote_host else "")
            session_rows.append(
                [
                    f"{session.get('started_at', '')[11:16]} - {session.get('ended_at', '')[11:16] if session.get('ended_at') else '進行中'}",
                    detail,
                ]
            )
        if len(session_rows) == 1:
            session_rows.append(["-", "セッション記録はありません。"])
        story.append(add_kv_table(session_rows, [40 * mm, 115 * mm]))

    elif export_name == "public_report":
        report = payload["report"]
        meta_rows = [
            ["作業項目数", str(len(report["report_items"])), "成果物数", str(report["artifact_count"])],
            ["リモート回数", str(report["remote_session_count"]), "編集ファイル数", str(report["edited_file_count"])],
        ]
        story.extend([add_kv_table(meta_rows, [32 * mm, 38 * mm, 32 * mm, 38 * mm]), Spacer(1, 10)])

        story.append(p("1. 要約", "ReportHeading"))
        story.append(p(report["narrative"]["outline"]))
        story.append(p(report["narrative"]["progress_paragraph"]))
        story.append(p(report["narrative"]["supporting_note"]))

        story.append(p("2. 次のアクション", "ReportHeading"))
        story.append(p(report["narrative"]["next_action_paragraph"]))

        story.append(p("3. 作業項目", "ReportHeading"))
        for item in report["report_items"] or ["作業項目はありません。"]:
            story.append(p(f"・{item}"))

        story.append(p("4. 参考情報", "ReportHeading"))
        info_rows = [
            ["成果物数", str(report["artifact_count"])],
            ["手動キャプチャ", str(report["manual_capture_count"])],
            ["主な接続先", " / ".join(report["remote_hosts"]) if report["remote_hosts"] else "なし"],
            ["主なファイル", report["top_files"][0]["path"] if report["top_files"] else "なし"],
        ]
        story.append(add_kv_table(info_rows, [42 * mm, 113 * mm]))

    elif export_name == "weekly_report":
        weekly = payload["weekly"]
        meta_rows = [
            ["総作業時間", f"{weekly['total_minutes']} min", "成果物数", str(weekly["artifact_count"])],
            ["コマンド数", str(weekly["command_count"]), "リモート時間", f"{weekly['remote_minutes']} min"],
        ]
        story.extend([add_kv_table(meta_rows, [32 * mm, 38 * mm, 32 * mm, 38 * mm]), Spacer(1, 10)])

        story.append(p("1. 週次総括", "ReportHeading"))
        story.append(p(weekly["narrative"]["overview"]))
        story.append(p(weekly["narrative"]["remote_note"]))
        story.append(p(f"来週の進め方: {weekly['narrative']['next_action']}"))

        story.append(p("2. 日別の進捗", "ReportHeading"))
        day_rows = [["日付", "内容"]]
        for day in weekly["days"]:
            body = day.get("narrative") or day.get("progress") or ""
            if day.get("top_task_name"):
                body += f"\n主タスク: {day['top_task_name']}"
            body += f"\n作業時間: {day['total_minutes']} min"
            day_rows.append([day["date_label"], body])
        if len(day_rows) == 1:
            day_rows.append(["-", "この週の記録はありません。"])
        story.extend([add_kv_table(day_rows, [35 * mm, 120 * mm]), Spacer(1, 8)])

        story.append(p("3. 編集ハイライト", "ReportHeading"))
        for item in weekly["edit_highlights"] or ["編集ハイライトはありません。"]:
            story.append(p(f"・{item}"))

    else:
        plain_text = _strip_html(payload.get("html", ""))
        for block in [item.strip() for item in plain_text.split("\n\n") if item.strip()]:
            story.append(p(block))

    story.append(Spacer(1, 6))
    story.append(p("Generated by Work Journal", "ReportSmall"))
    return story, A4, 15 * mm, 18 * mm


def save_pdf(path: Path, title: str, html: str, payload: dict | None = None, export_name: str = "") -> tuple[Path | None, str]:
    try:
        from reportlab.platypus import SimpleDocTemplate
    except Exception:
        return None, "PDF保存には reportlab のインストールが必要です。"

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        story, pagesize, left_margin, top_margin = _build_pdf_story(title, export_name, payload or {"html": html})
        doc = SimpleDocTemplate(
            str(path),
            pagesize=pagesize,
            title=title,
            leftMargin=left_margin,
            rightMargin=left_margin,
            topMargin=top_margin,
            bottomMargin=top_margin,
        )
        doc.build(story)
    except Exception as exc:
        return None, f"PDF生成に失敗しました: {exc}"
    return path, ""
