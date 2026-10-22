"""'OCR' for typed answer sheets: reads a .txt file as one page.

Lets the grader be built and evaluated on clean text (week 2) before real
OCR exists, and gives the clean-text arm of the OCR ablation.
"""

from __future__ import annotations

from pathlib import Path

from autoassess.providers.base import OCRProvider
from autoassess.schemas import OCRLine, OCRPage


class PlainTextOCR(OCRProvider):
    name = "text"

    def read_page(self, image_path: Path, page_index: int = 0, language_hint: str | None = None) -> OCRPage:
        text = Path(image_path).read_text(encoding="utf-8")
        lines = [OCRLine(text=t, confidence=1.0) for t in text.splitlines()]
        return OCRPage(page_index=page_index, image_path=str(image_path), lines=lines, provider=self.name)
