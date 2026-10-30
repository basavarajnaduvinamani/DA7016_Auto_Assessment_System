"""'OCR' for typed answer sheets: reads a .txt file as one page.

Reads typed answers without remote recognition and supplies clean text for input ablations.
"""

from __future__ import annotations

from pathlib import Path

from autoassess.providers.base import OCRProvider
from autoassess.schemas import OCRLine, OCRPage


class PlainTextOCR(OCRProvider):
    """Read typed text files through the common OCR interface."""

    name = "text"

    def read_page(self, image_path: Path, page_index: int = 0, language_hint: str | None = None) -> OCRPage:
        """Return non-empty text lines without recognition uncertainty."""
        text = Path(image_path).read_text(encoding="utf-8")
        lines = [OCRLine(text=t, confidence=1.0) for t in text.splitlines()]
        return OCRPage(page_index=page_index, image_path=str(image_path), lines=lines, provider=self.name)
