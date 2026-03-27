from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib import error, request

from .base import AIClientBase


class MistralAIClient(AIClientBase):
    provider_name = "mistral"
    api_url = "https://api.mistral.ai/v1/chat/completions"

    def summarize_screenshot(
        self,
        image_path: str,
        window_title: str = "",
        ocr_text: str = "",
    ) -> dict:
        api_key = os.getenv("MISTRAL_API_KEY", "")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY is not set")

        model = os.getenv("MISTRAL_VISION_MODEL", "mistral-small-latest")
        timeout = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30"))
        payload = {
            "model": model,
            "max_tokens": 180,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify desktop screenshots for a personal work journal. "
                        "Return JSON only with keys: activity_label, activity_summary, confidence. "
                        "activity_label must be one of: 実装・コード編集, コード確認, ドキュメント確認, "
                        "メール対応, チャット対応, CLI作業, 会議・打ち合わせ, 振り返り・日報確認, その他作業. "
                        "activity_summary should be a short Japanese sentence. confidence must be between 0 and 1."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this screenshot for a local work journal.\n"
                                f"Window title: {window_title or '(none)'}\n"
                                f"OCR text: {ocr_text or '(none)'}\n"
                                "Respond with JSON only."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": self._image_data_url(image_path),
                        },
                    ],
                },
            ],
            "response_format": {"type": "text"},
        }

        raw_response = self._post_json(payload=payload, api_key=api_key, timeout=timeout)
        message_text = self._extract_message_text(raw_response)
        parsed = self._parse_model_json(message_text)
        return {
            "activity_label": parsed["activity_label"],
            "activity_summary": parsed["activity_summary"],
            "confidence": parsed["confidence"],
            "raw_response": raw_response,
        }

    def _image_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _post_json(self, payload: dict, api_key: str, timeout: float) -> dict:
        req = request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mistral API error {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Mistral API connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Mistral API request timed out") from exc

    def _extract_message_text(self, response_json: dict) -> str:
        choices = response_json.get("choices") or []
        if not choices:
            raise RuntimeError("Mistral response did not include choices")
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                return str(content["text"])
            if isinstance(content.get("content"), str):
                return str(content["content"])
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(str(item.get("text", "")))
                elif isinstance(item.get("content"), str):
                    text_parts.append(str(item.get("content", "")))
            return "\n".join(part for part in text_parts if part).strip()
        raise RuntimeError("Mistral response content format was not recognized")

    def _parse_model_json(self, text: str) -> dict:
        candidate = text.strip()
        if "```" in candidate:
            pieces = candidate.split("```")
            candidate = next((piece for piece in pieces if "{" in piece and "}" in piece), candidate)
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end < start:
            return self._fallback_parse_text(candidate)
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return self._fallback_parse_text(candidate)
        label = str(parsed.get("activity_label", "その他作業")).strip() or "その他作業"
        summary = str(parsed.get("activity_summary", "")).strip() or "スクリーンショットの内容を要約しました"
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = min(1.0, max(0.0, confidence))
        return {
            "activity_label": label,
            "activity_summary": summary,
            "confidence": confidence,
        }

    def _fallback_parse_text(self, text: str) -> dict:
        normalized = text.replace("\r", "\n")
        label = "その他作業"
        summary = "スクリーンショットの内容を要約しました"
        confidence = 0.5

        for line in normalized.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower().replace("-", "_")
            value = value.strip().strip('"')
            if key.endswith("activity_label") or key == "label":
                label = value or label
            elif key.endswith("activity_summary") or key == "summary":
                summary = value or summary
            elif key.endswith("confidence"):
                try:
                    confidence = float(value)
                except ValueError:
                    pass

        return {
            "activity_label": label,
            "activity_summary": summary,
            "confidence": min(1.0, max(0.0, confidence)),
        }
