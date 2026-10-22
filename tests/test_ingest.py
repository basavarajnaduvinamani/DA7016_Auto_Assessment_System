import pytest

cv2 = pytest.importorskip("cv2")
pymupdf = pytest.importorskip("pymupdf")
import numpy as np

from autoassess.ingest import ingest


def test_pdf_to_clean_pages(tmp_path):
    pdf = tmp_path / "sheet.pdf"
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"Ans {i + 1}. Attention is a weighted sum of values.")
    doc.save(pdf)
    pages = ingest(pdf, tmp_path / "out")
    assert [p.name for p in pages] == ["page_000.png", "page_001.png"]
    img = cv2.imread(str(pages[0]), cv2.IMREAD_UNCHANGED)
    assert img.ndim == 2  # grayscale


def test_deskew_straightens_tilted_text(tmp_path):
    img = np.full((600, 800), 255, np.uint8)
    for y in range(100, 500, 40):
        cv2.line(img, (100, y), (700, y), 0, 6)
    m = cv2.getRotationMatrix2D((400, 300), 5, 1.0)
    tilted = cv2.warpAffine(img, m, (800, 600), borderValue=255)
    src = tmp_path / "tilted.png"
    cv2.imwrite(str(src), tilted)
    from autoassess.ingest import _deskew_angle

    before = abs(_deskew_angle(tilted))
    out = cv2.imread(str(ingest(src, tmp_path / "out")[0]), cv2.IMREAD_GRAYSCALE)
    assert before > 3
    assert abs(_deskew_angle(out)) < 1


def test_blank_and_show_through_pages_are_detected(tmp_path):
    from PIL import Image, ImageDraw

    from autoassess.ingest import is_blank

    blank = tmp_path / "blank.png"
    Image.new("RGB", (400, 600), "white").save(blank)
    ghost = tmp_path / "ghost.png"  # faint grey show-through only
    im = Image.new("RGB", (400, 600), "white")
    ImageDraw.Draw(im).text((20, 20), "mirrored text from the back " * 3, fill=(200, 200, 200))
    im.save(ghost)
    written = tmp_path / "written.png"
    im = Image.new("RGB", (400, 600), "white")
    d = ImageDraw.Draw(im)
    for y in range(20, 580, 30):
        d.line((20, y, 380, y), fill=(20, 20, 120), width=2)
    im.save(written)
    assert is_blank(blank) and not is_blank(written)
    assert is_blank(ghost, threshold=0.002)
