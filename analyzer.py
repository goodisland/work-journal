from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any


RULES = [
    {
        "label": "振り返り・日報確認",
        "summary": "作業ログや日報、振り返り内容を確認している可能性があります",
        "confidence": 0.93,
        "keywords": ["work journal mock", "private summary", "public report", "timeline", "dashboard"],
    },
    {
        "label": "実装・コード編集",
        "summary": "コードや設定ファイルを編集している可能性があります",
        "confidence": 0.92,
        "keywords": ["visual studio code", "vscode", "pycharm", "cursor", ".py", ".ts", ".js"],
    },
    {
        "label": "コード確認",
        "summary": "コードやリポジトリを確認している可能性があります",
        "confidence": 0.88,
        "keywords": ["github", "gitlab", "pull request", "sourcegraph"],
    },
    {
        "label": "ドキュメント確認",
        "summary": "仕様書やメモ、ドキュメントを確認している可能性があります",
        "confidence": 0.84,
        "keywords": ["docs", "notion", "confluence", "readme", "wiki", "spec"],
    },
    {
        "label": "メール対応",
        "summary": "メールを確認または返信している可能性があります",
        "confidence": 0.9,
        "keywords": ["gmail", "outlook", "inbox", "mail"],
    },
    {
        "label": "チャット対応",
        "summary": "チャットでやり取りしている可能性があります",
        "confidence": 0.9,
        "keywords": ["slack", "teams", "discord", "chatwork"],
    },
    {
        "label": "CLI作業",
        "summary": "ターミナルやシェルで作業している可能性があります",
        "confidence": 0.9,
        "keywords": ["terminal", "powershell", "cmd.exe", "iterm", "windows terminal"],
    },
    {
        "label": "会議・打ち合わせ",
        "summary": "会議や通話をしている可能性があります",
        "confidence": 0.82,
        "keywords": ["zoom", "meet", "teams meeting", "webex"],
    },
]

DEFAULT_RESULT = {
    "activity_label": "その他作業",
    "activity_summary": "作業内容を特定できなかったため、その他作業として記録しました",
    "confidence": 0.45,
}


def extract_ocr_text(image_path: str) -> str:
    try:
        command = [
            sys.executable,
            "-c",
            (
                "import pytesseract; "
                "from PIL import Image; "
                "print(pytesseract.image_to_string(Image.open(r'''%s'''), lang='eng+jpn'))"
            )
            % image_path.replace("\\", "\\\\"),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=float(os.getenv("OCR_TIMEOUT_SECONDS", "15")),
            encoding="utf-8",
            errors="ignore",
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()
    except Exception:
        return ""


def summarize_rule_based(window_title: str = "", ocr_text: str = "") -> dict[str, Any]:
    combined = f"{window_title} {ocr_text}".lower()
    for rule in RULES:
        if any(keyword in combined for keyword in rule["keywords"]):
            return {
                "activity_label": rule["label"],
                "activity_summary": rule["summary"],
                "confidence": rule["confidence"],
            }
    return DEFAULT_RESULT.copy()


def mask_sensitive_content(image_path: str, ocr_text: str) -> tuple[str, str]:
    # Future extension point for masking passwords, emails, project names and other secrets.
    masked_text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[masked-email]", ocr_text)
    masked_text = re.sub(r"\bsk-[A-Za-z0-9]+\b", "[masked-key]", masked_text)
    return image_path, masked_text


def summarize_screenshot_with_ai(
    image_path: str,
    window_title: str = "",
    ocr_text: str = "",
    provider: str = "mock",
) -> dict:
    from ai_clients import get_ai_client

    client = get_ai_client(provider)
    return client.summarize_screenshot(
        image_path=image_path,
        window_title=window_title,
        ocr_text=ocr_text,
    )


def analyze_activity(
    image_path: str,
    window_title: str = "",
    enable_ocr: bool = False,
    use_ai: bool | None = None,
    ai_provider: str | None = None,
    ai_threshold: float | None = None,
) -> dict[str, Any]:
    ocr_text = extract_ocr_text(image_path) if enable_ocr else ""
    masked_image_path, masked_text = mask_sensitive_content(image_path, ocr_text)
    rule_result = summarize_rule_based(window_title=window_title, ocr_text=masked_text)

    provider = ai_provider or os.getenv("AI_PROVIDER", "mock")
    ai_enabled = (
        use_ai
        if use_ai is not None
        else os.getenv("AI_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    )
    threshold = (
        ai_threshold
        if ai_threshold is not None
        else float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.6"))
    )

    result = {
        "window_title": window_title,
        "ocr_text": masked_text,
        "activity_label": rule_result["activity_label"],
        "activity_summary": rule_result["activity_summary"],
        "confidence": rule_result["confidence"],
        "inference_source": "rule_based",
        "ai_provider": "",
        "ai_called": False,
        "ai_error": "",
    }

    if not (ai_enabled and rule_result["confidence"] < threshold):
        return result

    result["ai_called"] = True
    try:
        ai_result = summarize_screenshot_with_ai(
            image_path=masked_image_path,
            window_title=window_title,
            ocr_text=masked_text,
            provider=provider,
        )
        result.update(
            {
                "activity_label": ai_result["activity_label"],
                "activity_summary": ai_result["activity_summary"],
                "confidence": float(ai_result["confidence"]),
                "inference_source": "ai",
                "ai_provider": provider,
            }
        )
    except Exception as exc:
        result["ai_error"] = str(exc)

    return result
