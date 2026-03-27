from __future__ import annotations

import ctypes
import threading
import time
from datetime import datetime
from pathlib import Path

from analyzer import analyze_activity
from storage import append_log, get_screenshot_path

try:
    import mss
except Exception:  # pragma: no cover
    mss = None

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None


def get_active_window_title() -> str:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value.strip()
    except Exception:
        return ""


def capture_screenshot(output_path: Path) -> None:
    if mss:
        with mss.mss() as sct:
            sct.shot(output=str(output_path))
            return
    create_placeholder_screenshot(output_path, "screenshot unavailable")


def create_placeholder_screenshot(output_path: Path, label: str) -> None:
    if Image and ImageDraw:
        image = Image.new("RGB", (1280, 720), color=(246, 241, 232))
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 1240, 180), fill=(31, 53, 79))
        draw.text((70, 85), "Work Journal Mock", fill=(255, 255, 255))
        draw.text((70, 125), label[:80], fill=(255, 255, 255))
        draw.rectangle((40, 220, 1240, 680), fill=(230, 223, 208))
        draw.text((70, 270), "This is a fallback image used when live capture is not available.", fill=(31, 53, 79))
        image.save(output_path)
        return

    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?"
        b"\x00\x05\xfe\x02\xfeA\xdd\x94\x89\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    output_path.write_bytes(tiny_png)


class RecorderService:
    def __init__(
        self,
        interval_seconds: int = 5,
        enable_ocr: bool = False,
        use_ai: bool = False,
        ai_provider: str = "mock",
        ai_threshold: float = 0.6,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.enable_ocr = enable_ocr
        self.use_ai = use_ai
        self.ai_provider = ai_provider
        self.ai_threshold = ai_threshold
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self.is_running:
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self.is_running:
                return False
            self._stop_event.set()
            return True

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_settings(
        self,
        interval_seconds: int | None = None,
        enable_ocr: bool | None = None,
        use_ai: bool | None = None,
        ai_provider: str | None = None,
        ai_threshold: float | None = None,
    ) -> None:
        if interval_seconds is not None:
            self.interval_seconds = max(3, interval_seconds)
        if enable_ocr is not None:
            self.enable_ocr = enable_ocr
        if use_ai is not None:
            self.use_ai = use_ai
        if ai_provider is not None:
            self.ai_provider = ai_provider
        if ai_threshold is not None:
            self.ai_threshold = ai_threshold

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            started_at = time.time()
            self.record_once()
            elapsed = time.time() - started_at
            self._stop_event.wait(max(0.5, self.interval_seconds - elapsed))

    def record_once(self) -> dict:
        ts = datetime.now().replace(microsecond=0)
        output_path = get_screenshot_path(ts)
        window_title = get_active_window_title()

        try:
            capture_screenshot(output_path)
        except Exception:
            create_placeholder_screenshot(output_path, window_title or "capture failed")

        analysis = analyze_activity(
            image_path=str(output_path),
            window_title=window_title,
            enable_ocr=self.enable_ocr,
            use_ai=self.use_ai,
            ai_provider=self.ai_provider,
            ai_threshold=self.ai_threshold,
        )
        entry = {
            "timestamp": ts.isoformat(),
            "screenshot_path": str(output_path.relative_to(Path(__file__).resolve().parent)).replace("\\", "/"),
            **analysis,
        }
        append_log(entry)
        return entry
