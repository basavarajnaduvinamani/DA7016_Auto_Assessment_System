"""OCR baseline: a vision-capable LLM transcribes the page.

Works with any OpenAI-compatible endpoint that accepts image inputs (for
example a vision model on OpenRouter). It gives no boxes or confidences, so
the report cannot highlight evidence on the page; it is the comparison arm
for IndicOCR in the OCR ablation.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.request
from pathlib import Path

from autoassess.budget import Ledger, record_llm_cost
from autoassess.cache import DiskCache, content_key
from autoassess.providers.base import OCRProvider
from autoassess.schemas import OCRLine, OCRPage

VISION_OCR_PROMPT = """Transcribe this handwritten or printed exam answer page exactly.
- Keep the student's words, spelling and line breaks; do not correct anything.
- Keep question labels such as "Q2", "Ans 3" or "3." exactly as written.
- Write equations in LaTeX between $ signs.
- Write [diagram] for a drawing and [illegible] for words you cannot read.
Return only the transcription."""


class VisionLLMOCR(OCRProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        cache: DiskCache | None = None,
        timeout: float = 180,
        ledger: Ledger | None = None,
    ):
        if not model:
            raise ValueError("no vision model configured; set AUTOASSESS_VISION_MODEL")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.cache = cache
        self.timeout = timeout
        self.ledger = ledger
        self.name = f"vision-llm:{model}"

    def _transcribe(self, image: bytes, mime: str) -> str:
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
        )
        if self.ledger:
            self.ledger.check()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            response = json.loads(resp.read())
        record_llm_cost(self.ledger, response)
        return response["choices"][0]["message"]["content"]

    def read_page(self, image_path: Path, page_index: int, language_hint: str | None = None) -> OCRPage:
        image = Path(image_path).read_bytes()
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        if self.cache is None:
            text = self._transcribe(image, mime)
        else:
            text = self.cache.get_or_compute(content_key("vision-ocr", self.model, image), lambda: self._transcribe(image, mime))
        lines = [
            OCRLine(text=t, kind="diagram" if t.strip() == "[diagram]" else "text")
            for t in text.splitlines()
            if t.strip()
        ]
        return OCRPage(page_index=page_index, image_path=str(image_path), lines=lines, provider=self.name)
