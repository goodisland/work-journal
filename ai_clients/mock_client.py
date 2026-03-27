from __future__ import annotations

from analyzer import summarize_rule_based

from .base import AIClientBase


class MockAIClient(AIClientBase):
    provider_name = "mock"

    def summarize_screenshot(
        self,
        image_path: str,
        window_title: str = "",
        ocr_text: str = "",
    ) -> dict:
        base_result = summarize_rule_based(window_title=window_title, ocr_text=ocr_text)
        return {
            "activity_label": base_result["activity_label"],
            "activity_summary": f"{base_result['activity_summary']} (mock AI)",
            "confidence": min(0.95, base_result["confidence"] + 0.08),
            "raw_response": {
                "image_path": image_path,
                "window_title": window_title,
                "ocr_text": ocr_text,
                "provider": self.provider_name,
            },
        }
