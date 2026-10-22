"""Bodhan AI hosted APIs: IndicOCR and Indic-Translate.

Request shapes follow Bodhan's cookbook (github.com/Bodhan-AI/Bodhan-AI-Cookbook):
- OCR: POST {base}/v1/chat/completions, model "indic-ocr", one page image as a
  base64 data URL. The response carries Markdown in choices[0].message.content
  and layout `blocks` (order, label, type, bbox_xyxy, conf, text), the same
  block format as the open weights, so blocks_to_page converts it.
- Translate: POST {base}/translate with text and target_language (a code such
  as "hi" or "kn"); the source language is detected. Billed on output tokens.
Errors come back as {"error": {"message", "code", "request_id"}}.

Every call is cached by content, so no page or sentence is paid for twice, and
a small ledger stops paid calls once BODHAN_BUDGET_INR is reached.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

from autoassess.budget import BudgetExceeded, Ledger, bodhan_ledger
from autoassess.cache import DiskCache, content_key
from autoassess.providers.base import OCRProvider, Translator
from autoassess.providers.indic_ocr import blocks_to_page
from autoassess.schemas import OCRPage

__all__ = ["BodhanError", "BodhanOCR", "BodhanTranslate", "BudgetExceeded", "Ledger", "language_code"]

DEFAULT_BASE_URL = "https://api.bodhan.ai"
OCR_INR_PER_PAGE = 0.20
TRANSLATE_INR_PER_10K_OUTPUT_TOKENS = 0.20

LANGUAGE_CODES = {
    "assamese": "as", "bengali": "bn", "bodo": "brx", "dogri": "doi", "english": "en", "gujarati": "gu",
    "hindi": "hi", "kannada": "kn", "konkani": "kok", "kashmiri": "ks", "maithili": "mai", "malayalam": "ml",
    "manipuri": "mni", "marathi": "mr", "nepali": "ne", "odia": "or", "oriya": "or", "punjabi": "pa",
    "sanskrit": "sa", "santali": "sat", "sindhi": "sd", "tamil": "ta", "telugu": "te", "urdu": "ur",
}  # fmt: skip


def language_code(language: str) -> str:
    """'Kannada' or 'kn' -> 'kn'."""
    if "-" in language:
        return language.strip()  # script variants such as "sd-Arab" are case-sensitive
    key = language.strip().lower()
    if key in LANGUAGE_CODES.values():
        return key
    if key not in LANGUAGE_CODES:
        raise ValueError(f"Bodhan does not list language {language!r}")
    return LANGUAGE_CODES[key]


class BodhanError(RuntimeError):
    pass


class _BodhanClient:
    def __init__(self, api_key: str, base_url: str, cache: DiskCache | None, budget_inr: float | None, timeout: float):
        if not api_key:
            raise ValueError("BODHAN_API_KEY is not set; get a key at console.bodhan.ai")
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/").removesuffix("/v1")
        self.cache = cache
        self.timeout = timeout
        self.ledger: Ledger = bodhan_ledger(cache.dir.parent if cache else Path(".cache"), budget_inr)

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            try:
                e = json.loads(err.read())["error"]
                msg = f"{err.code} {e.get('code')}: {e.get('message')} (request_id={e.get('request_id')})"
            except (ValueError, KeyError, TypeError):
                msg = f"{err.code} {err.reason}"
            raise BodhanError(msg) from err


class BodhanOCR(OCRProvider):
    name = "bodhan-indicocr"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, cache: DiskCache | None = None, budget_inr: float | None = None, timeout: float = 180):
        self.client = _BodhanClient(api_key, base_url, cache, budget_inr, timeout)

    def _ocr(self, image: bytes, mime: str) -> dict:
        self.client.ledger.check(OCR_INR_PER_PAGE)
        body = {
            "model": "indic-ocr",
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}}]}],
            "table_format": "markdown",
        }
        result = self.client._post("/v1/chat/completions", body)
        self.client.ledger.add(OCR_INR_PER_PAGE)
        return {"blocks": result.get("blocks", []), "markdown": result["choices"][0]["message"]["content"]}

    def read_page(self, image_path: Path, page_index: int, language_hint: str | None = None) -> OCRPage:
        image = Path(image_path).read_bytes()
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        cache = self.client.cache
        parsed = (
            cache.get_or_compute(content_key("bodhan-ocr", image), lambda: self._ocr(image, mime))
            if cache
            else self._ocr(image, mime)
        )
        if not parsed.get("blocks") and parsed.get("markdown"):
            # No layout blocks: fall back to the Markdown, one line per line, no boxes.
            parsed = {"blocks": [{"order": 0, "type": "Text", "text": parsed["markdown"]}]}
        return blocks_to_page(parsed, page_index, str(image_path), self.name)


class BodhanTranslate(Translator):
    name = "bodhan-indic-translate"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, cache: DiskCache | None = None, budget_inr: float | None = None, timeout: float = 60):
        self.client = _BodhanClient(api_key, base_url, cache, budget_inr, timeout)

    def _translate(self, text: str, code: str) -> str:
        # Cost is billed on output tokens; assume output about as long as the input.
        estimate = TRANSLATE_INR_PER_10K_OUTPUT_TOKENS * max(1, len(text) // 3) / 10_000
        self.client.ledger.check(estimate)
        out = self.client._post("/translate", {"text": text, "target_language": code})
        tokens = (out.get("usage") or {}).get("output_tokens")
        self.client.ledger.add(TRANSLATE_INR_PER_10K_OUTPUT_TOKENS * tokens / 10_000 if tokens else estimate)
        if out.get("truncated"):
            raise BodhanError("translation was truncated; split the text into shorter parts")
        return out["translation"]

    def translate(self, text: str, target_language: str, source_language: str = "English") -> str:
        code = language_code(target_language)
        if code == "en" or not text.strip():
            return text
        # Paragraph by paragraph keeps requests short and avoids truncation.
        parts = []
        for para in text.split("\n"):
            if not para.strip():
                parts.append(para)
                continue
            cache = self.client.cache
            parts.append(
                cache.get_or_compute(content_key("bodhan-translate", code, para), lambda p=para: self._translate(p, code))
                if cache
                else self._translate(para, code)
            )
        return "\n".join(parts)
