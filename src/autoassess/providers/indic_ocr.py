"""Bodhan IndicOCR, run from its open weights (bodhan-ai/indic-ocr on Hugging Face).

IndicOCR = a layout detector (IndicDocLayout) + a block recogniser
(IndicBlockOCR). `parse(image)` returns the page's blocks in reading order,
each with `order`, `type`, `bbox_xyxy`, `conf` and `text`. Handwriting is
supported for English and 12 Indian languages, including Hindi, Kannada,
Tamil and Telugu.

The weights are gated: accept the Indic Open Model License on Hugging Face,
then on a GPU machine (a free Colab or Kaggle notebook is enough):

    from huggingface_hub import snapshot_download
    repo = snapshot_download("bodhan-ai/indic-ocr")   # then run repo/install.sh

Two providers live here:
- IndicOCRLocal runs the model in-process (needs the GPU machine).
- PrecomputedOCR reads page JSON files that IndicOCR already wrote, so OCR
  can run once in a notebook and grading can run anywhere afterwards
  (notebooks/indic_ocr_colab.ipynb does the first half).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from autoassess.providers.base import OCRProvider
from autoassess.schemas import BBox, OCRLine, OCRPage

# Coarse block types that carry no answer text.
_SKIP_TYPES = {"pageheader", "pagefooter", "pagenumber", "header", "footer", "advertisement"}
_DIAGRAM_TYPES = {"figure", "picture", "image", "chart", "diagram"}


def blocks_to_page(parsed: dict[str, Any], page_index: int, image_path: str | None = None, provider: str = "indic-ocr") -> OCRPage:
    """Convert IndicOCR's parse() output into an OCRPage, one line per text line."""
    blocks = sorted(parsed.get("blocks", []), key=lambda b: b.get("order", 0))
    lines: list[OCRLine] = []
    for b in blocks:
        kind_raw = str(b.get("type") or b.get("label") or "Text").lower()
        if kind_raw in _SKIP_TYPES:
            continue
        box = b.get("bbox_xyxy")
        bbox = BBox(x0=box[0], y0=box[1], x1=box[2], y1=box[3]) if box and len(box) == 4 else None
        conf = b.get("conf")
        conf = min(max(float(conf), 0.0), 1.0) if conf is not None else None
        if kind_raw in _DIAGRAM_TYPES:
            lines.append(OCRLine(text="[diagram]", bbox=bbox, confidence=conf, kind="diagram"))
            continue
        kind = "equation" if kind_raw in {"equation", "formula"} else "text"
        for text in str(b.get("text") or "").splitlines():
            if text.strip():
                lines.append(OCRLine(text=text.rstrip(), bbox=bbox, confidence=conf, kind=kind))
    return OCRPage(page_index=page_index, image_path=image_path, lines=lines, provider=provider)


class IndicOCRLocal(OCRProvider):
    name = "indic-ocr-local"

    def __init__(self, repo_dir: str | Path | None = None, parser: Any = None):
        """repo_dir: a snapshot of bodhan-ai/indic-ocr. `parser` is for tests."""
        if parser is None:
            if repo_dir is None:
                from huggingface_hub import snapshot_download

                repo_dir = snapshot_download("bodhan-ai/indic-ocr")
            sys.path.insert(0, str(repo_dir))
            from indic_ocr import IndicOCR  # shipped inside the model repo

            parser = IndicOCR.from_pretrained(str(repo_dir), table_format="markdown")
        self.parser = parser

    def read_page(self, image_path: Path, page_index: int, language_hint: str | None = None) -> OCRPage:
        return blocks_to_page(self.parser.parse(str(image_path)), page_index, str(image_path), self.name)


class PrecomputedOCR(OCRProvider):
    """Reads `<image stem>.json` (IndicOCR parse() output) from a folder."""

    name = "indic-ocr-precomputed"

    def __init__(self, json_dir: str | Path):
        self.json_dir = Path(json_dir)

    def read_page(self, image_path: Path, page_index: int, language_hint: str | None = None) -> OCRPage:
        path = self.json_dir / f"{Path(image_path).stem}.json"
        if not path.exists():
            raise FileNotFoundError(f"no precomputed OCR for {image_path} (expected {path})")
        return blocks_to_page(json.loads(path.read_text(encoding="utf-8")), page_index, str(image_path), self.name)
