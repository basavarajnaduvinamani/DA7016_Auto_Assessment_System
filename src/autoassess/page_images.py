"""Page images for the grader: the crop of each page that holds one answer.

Used by the "image" and "hybrid" input modes. When the OCR gave line boxes,
the crop is the union of the answer's boxes plus a margin, so the model sees
diagrams and crossed-out work around the text; otherwise the whole page is
sent. Images are downscaled so the long side is at most max_side pixels,
which keeps vision calls cheap.
"""

from __future__ import annotations

import io
from pathlib import Path

from autoassess.schemas import AnswerSegment, OCRPage


def answer_crops(segment: AnswerSegment, pages: list[OCRPage], max_side: int = 1600, margin: int = 40) -> list[bytes]:
    """Crop the page regions associated with an answer segment for vision grading."""
    from PIL import Image

    by_index = {p.page_index: p for p in pages}
    seg_lines = {id(line) for line in segment.lines}
    out = []
    for idx in segment.pages:
        page = by_index.get(idx)
        if page is None or not page.image_path or not Path(page.image_path).exists():
            continue
        with Image.open(page.image_path) as im:
            im = im.convert("RGB")
            boxes = [line.bbox for line in page.lines if id(line) in seg_lines and line.bbox]
            if boxes:
                w, h = im.size
                x0 = max(0, min(b.x0 for b in boxes) - margin)
                y0 = max(0, min(b.y0 for b in boxes) - margin)
                x1 = min(w, max(b.x1 for b in boxes) + margin)
                y1 = min(h, max(b.y1 for b in boxes) + margin)
                # Keep the full width: margins and diagrams beside the text matter.
                im = im.crop((0, y0, w, y1)) if x1 - x0 < w * 0.8 else im.crop((x0, y0, x1, y1))
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            out.append(buf.getvalue())
    return out
