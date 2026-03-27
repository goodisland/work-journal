from __future__ import annotations

import os

from .base import AIClientBase


class OpenAIClient(AIClientBase):
    provider_name = "openai"

    def summarize_screenshot(
        self,
        image_path: str,
        window_title: str = "",
        ocr_text: str = "",
    ) -> dict:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        # Future extension point:
        # - mask_sensitive_content() before upload
        # - call a vision-capable model with image + metadata
        # - parse activity_label / activity_summary / confidence JSON
        raise NotImplementedError("OpenAI integration is a scaffold in this mock")
