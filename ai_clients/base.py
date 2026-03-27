from __future__ import annotations

from abc import ABC, abstractmethod


class AIClientBase(ABC):
    provider_name = "base"

    @abstractmethod
    def summarize_screenshot(
        self,
        image_path: str,
        window_title: str = "",
        ocr_text: str = "",
    ) -> dict:
        raise NotImplementedError
