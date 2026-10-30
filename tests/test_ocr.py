import json

import pytest
from conftest import SAMPLE, FakeLLM

from autoassess.grader import grade_question
from autoassess.providers.indic_ocr import IndicOCRLocal, PrecomputedOCR, blocks_to_page
from autoassess.schemas import AnswerSegment, OCRLine
from autoassess.segment import segment_pages
from autoassess.spec_builder import load_spec

SPEC = load_spec(SAMPLE / "exam_spec.yaml")

PARSED = {
    "width": 800,
    "height": 1273,
    "blocks": [
        {
            "order": 2,
            "type": "Text",
            "bbox_xyxy": [50, 300, 700, 380],
            "conf": 0.91,
            "text": "Ans 2. Hallucination is fluent\nbut false text.",
        },
        {"order": 0, "type": "PageHeader", "bbox_xyxy": [50, 10, 700, 40], "conf": 0.99, "text": "Roll No 23"},
        {
            "order": 1,
            "type": "Text",
            "bbox_xyxy": [50, 100, 700, 280],
            "conf": 0.88,
            "text": "Ans 1. Queries keys and values",
        },
        {"order": 3, "type": "Figure", "bbox_xyxy": [50, 400, 700, 600], "conf": 0.7, "text": ""},
        {
            "order": 4,
            "type": "Equation",
            "bbox_xyxy": [50, 620, 700, 660],
            "conf": 0.8,
            "text": "softmax(QK^T / sqrt(d_k)) V",
        },
        {"order": 5, "type": "PageNumber", "bbox_xyxy": [380, 1240, 420, 1260], "conf": 0.9, "text": "1"},
    ],
}


def test_blocks_to_page_orders_and_filters():
    page = blocks_to_page(PARSED, 0, "p.png")
    assert [line.text for line in page.lines] == [
        "Ans 1. Queries keys and values",
        "Ans 2. Hallucination is fluent",
        "but false text.",
        "[diagram]",
        "softmax(QK^T / sqrt(d_k)) V",
    ]
    assert page.lines[0].bbox.y0 == 100 and page.lines[0].confidence == 0.88
    assert [line.kind for line in page.lines[3:]] == ["diagram", "equation"]


def test_segmentation_on_ocr_page_keeps_boxes():
    seg = segment_pages(SPEC, [blocks_to_page(PARSED, 0)])
    assert seg["Q1"].text == "Queries keys and values"
    assert seg["Q2"].text.startswith("Hallucination is fluent\nbut false text.")
    assert all(line.bbox is not None for line in seg["Q2"].lines)


def test_local_provider_uses_parser():
    class P:
        def parse(self, path):
            return PARSED

    page = IndicOCRLocal(parser=P()).read_page("x.png", 3)
    assert page.page_index == 3 and page.provider == "indic-ocr-local"


def test_precomputed_reads_json(tmp_path):
    (tmp_path / "page_000.json").write_text(json.dumps(PARSED))
    page = PrecomputedOCR(tmp_path).read_page(tmp_path / "page_000.png", 0)
    assert len(page.lines) == 5
    with pytest.raises(FileNotFoundError):
        PrecomputedOCR(tmp_path).read_page(tmp_path / "page_009.png", 9)


def test_low_ocr_confidence_and_diagram_flags():
    q = SPEC.question("Q2")
    seg = AnswerSegment(
        question_id="Q2",
        text="fluent but false",
        lines=[
            OCRLine(text="fluent but false", confidence=0.4),
            OCRLine(text="[diagram]", kind="diagram", confidence=0.6),
        ],
    )
    reply = {
        "criteria": [{"criterion_id": c.id, "marks_awarded": 0, "evidence": None, "reason": ""} for c in q.criteria]
    }
    g = grade_question(q, seg, FakeLLM([reply]), runs=1)
    assert g.flags == ["low_ocr_confidence", "contains_diagram"]


def test_pdf_sheet_through_precomputed_ocr(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("cv2")
    from autoassess.pipeline import grade_pages, read_sheet

    pdf = tmp_path / "S010.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Ans 1. Queries keys and values")
    doc.save(pdf)
    (tmp_path / "json").mkdir()
    (tmp_path / "json" / "page_000.json").write_text(json.dumps(PARSED))
    pages = read_sheet(pdf, PrecomputedOCR(tmp_path / "json"), work_dir=tmp_path / "work")
    grade = grade_pages(SPEC, pages, "S010", None)
    assert grade.questions[0].marks_awarded > 0
    assert grade.questions[2].flags == ["unanswered"]
