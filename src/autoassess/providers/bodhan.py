"""Bodhan AI providers (week 5).

Bodhan's hosted APIs use OpenAI-compatible request shapes at
https://api.bodhan.ai/v1, with a key per model from the Bodhan API console.
IndicOCR costs about Rs 0.20 per image and Indic-Translate about Rs 0.20 per
10,000 output tokens. The exact OCR request and response shapes are not public
yet, so these classes are placeholders: fill them in from the console docs
once the coupon is redeemed. During development, run the open IndicOCR weights
from Hugging Face on a free Colab or Kaggle GPU instead.
"""

from __future__ import annotations

from pathlib import Path

from autoassess.cache import DiskCache
from autoassess.providers.base import OCRProvider, Translator
from autoassess.schemas import OCRPage


class BodhanOCR(OCRProvider):
    name = "bodhan-indicocr"

    def __init__(self, api_key: str, base_url: str = "https://api.bodhan.ai/v1", cache: DiskCache | None = None):
        if not api_key:
            raise ValueError("BODHAN_API_KEY is not set; Bodhan OCR is planned for week 5")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache

    def read_page(self, image_path: Path, page_index: int, language_hint: str | None = None) -> OCRPage:
        # TODO(week 5): send the page image, map blocks to OCRLine with bbox and
        # confidence, and cache on content_key("bodhan-ocr", image bytes).
        raise NotImplementedError("Bodhan IndicOCR integration lands in week 5")


class BodhanTranslate(Translator):
    name = "bodhan-indic-translate"

    def __init__(self, api_key: str, base_url: str = "https://api.bodhan.ai/v1", cache: DiskCache | None = None):
        if not api_key:
            raise ValueError("BODHAN_API_KEY is not set; Bodhan translation is planned for week 5")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache

    def translate(self, text: str, target_language: str, source_language: str = "English") -> str:
        # TODO(week 5): the model card's prompt format is
        # "Translate the following text into <Language>:" followed by the text.
        raise NotImplementedError("Bodhan Indic-Translate integration lands in week 5")
