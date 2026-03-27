from __future__ import annotations

import base64
from datetime import datetime, timedelta
from pathlib import Path

from storage import SAMPLE_LOG_PATH, SCREENSHOTS_DIR, write_log_file


def create_placeholder_screenshot(output_path: Path) -> None:
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )
    output_path.write_bytes(tiny_png)


def ensure_sample_data() -> None:
    if SAMPLE_LOG_PATH.exists():
        return

    day = "2026-03-27"
    base_dir = SCREENSHOTS_DIR / day
    base_dir.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat("2026-03-27T09:30:00")

    samples = [
        ("Visual Studio Code - app.py", "実装・コード編集", "FastAPIの画面とバックエンドを実装している可能性があります", 0.92, "rule_based"),
        ("Google Chrome - GitHub Pull Request", "コード確認", "GitHub上でコードや差分を確認している可能性があります", 0.88, "rule_based"),
        ("Notion - daily notes", "ドキュメント確認", "ドキュメントやメモを参照している可能性があります", 0.84, "rule_based"),
        ("Slack | Team Channel", "チャット対応", "関係者とチャットで調整している可能性があります", 0.9, "rule_based"),
        ("Windows PowerShell", "CLI作業", "PowerShellで開発支援の作業をしている可能性があります", 0.9, "ai"),
        ("Outlook", "メール対応", "メール確認や返信をしている可能性があります", 0.9, "rule_based"),
    ]

    entries: list[dict] = []
    for index, sample in enumerate(samples):
        ts = start + timedelta(minutes=index * 7)
        filename = f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}.png"
        image_path = base_dir / filename
        create_placeholder_screenshot(image_path)
        entries.append(
            {
                "timestamp": ts.isoformat(),
                "screenshot_path": f"data/screenshots/{day}/{filename}",
                "window_title": sample[0],
                "ocr_text": "",
                "activity_label": sample[1],
                "activity_summary": sample[2],
                "confidence": sample[3],
                "inference_source": sample[4],
                "ai_provider": "mock" if sample[4] == "ai" else "",
                "ai_called": sample[4] == "ai",
                "ai_error": "",
            }
        )

    write_log_file(SAMPLE_LOG_PATH, entries)


if __name__ == "__main__":
    ensure_sample_data()
    print(f"Sample data ready: {Path(SAMPLE_LOG_PATH).resolve()}")
