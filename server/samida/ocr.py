from pathlib import Path
from threading import Lock

from rapidocr import RapidOCR


class OcrService:
    """Local OCR with lazy model initialization."""

    def __init__(self) -> None:
        self._engine: RapidOCR | None = None
        self._lock = Lock()

    def extract_text(self, image_path: Path) -> str:
        with self._lock:
            if self._engine is None:
                self._engine = RapidOCR()
            result = self._engine(str(image_path))
        if not result or not result.txts:
            return ""
        lines = [text.strip() for text in result.txts if text and text.strip()]
        return "\n".join(lines)

