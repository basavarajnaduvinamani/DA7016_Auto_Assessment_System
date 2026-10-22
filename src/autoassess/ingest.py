"""Ingest: answer sheet PDF or photos -> cleaned page images.

Needs the optional 'ingest' extras: pip install -e ".[ingest]"
"""

from __future__ import annotations

from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def pdf_to_images(pdf_path: str | Path, out_dir: str | Path, dpi: int = 200) -> list[Path]:
    import pymupdf

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            p = out_dir / f"page_{i:03d}.png"
            page.get_pixmap(dpi=dpi).save(p)
            paths.append(p)
    return paths


def _deskew_angle(gray) -> float:
    import cv2
    import numpy as np

    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 50:
        return 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype("float32"))[-1]
    if angle > 45:
        angle -= 90
    # Only correct small tilts; large angles are usually layout, not skew.
    return float(angle) if abs(angle) <= 15 else 0.0


def clean_page(image_path: str | Path, out_path: str | Path) -> Path:
    """Grayscale, deskew, and even out contrast (CLAHE)."""
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"cannot read image {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    angle = _deskew_angle(gray)
    if angle:
        h, w = gray.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        gray = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), gray)
    return out_path


def ingest(source: str | Path, out_dir: str | Path, dpi: int = 200) -> list[Path]:
    """PDF, a single image, or a folder of images -> cleaned pages in out_dir, in order."""
    source, out_dir = Path(source), Path(out_dir)
    raw_dir = out_dir / "raw"
    if source.is_dir():
        raw = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    elif source.suffix.lower() == ".pdf":
        raw = pdf_to_images(source, raw_dir, dpi)
    elif source.suffix.lower() in IMAGE_SUFFIXES:
        raw = [source]
    else:
        raise ValueError(f"unsupported input {source}")
    return [clean_page(p, out_dir / f"page_{i:03d}.png") for i, p in enumerate(raw)]
