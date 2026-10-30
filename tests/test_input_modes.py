"""OCR text vs page image vs both: the grader's input modes and the answer crops."""

import io

import pytest
from conftest import SAMPLE, FakeLLM
from PIL import Image

from autoassess.experiments import run_ablation
from autoassess.grader import grade_question, grade_sheet
from autoassess.page_images import answer_crops
from autoassess.schemas import AnswerSegment, BBox, OCRLine, OCRPage
from autoassess.spec_builder import load_spec

SPEC = load_spec(SAMPLE / "exam_spec.yaml")
Q2 = SPEC.question("Q2")
TEXT = "Hallucination is confident text that is not true."
REPLY = {"criteria": [
    {"criterion_id": "Q2.c1", "marks_awarded": 1.5, "evidence": "confident text that is not true", "reason": "r"},
    {"criterion_id": "Q2.c2", "marks_awarded": 0, "evidence": None, "reason": "r"},
    {"criterion_id": "Q2.c3", "marks_awarded": 0, "evidence": None, "reason": "r"},
]}  # fmt: skip


class VisionFake(FakeLLM):
    def __init__(self, replies):
        super().__init__(replies)
        self.image_calls = []

    def complete_json_images(self, system, user, images, *, temperature=0.0, seed=None):
        self.image_calls.append((user, len(images)))
        return self.replies.pop(0)


def _page(tmp_path, h=1200):
    path = tmp_path / "p0.png"
    Image.new("RGB", (900, h), "white").save(path)
    line = OCRLine(text=f"Ans 2 {TEXT}", bbox=BBox(x0=50, y0=400, x1=850, y1=460))
    return OCRPage(
        page_index=0,
        image_path=str(path),
        lines=[OCRLine(text="Ans 1 x", bbox=BBox(x0=50, y0=100, x1=850, y1=150)), line],
    )


def test_crop_is_the_answer_band_not_the_whole_page(tmp_path):
    page = _page(tmp_path)
    seg = AnswerSegment(question_id="Q2", text=TEXT, pages=[0], lines=[page.lines[1]])
    (crop,) = answer_crops(seg, [page])
    w, h = Image.open(io.BytesIO(crop)).size
    assert (w, h) == (880, 140)  # the text box plus a 40px margin all round


def test_hybrid_sends_images_and_still_checks_quotes():
    llm = VisionFake([REPLY])
    g = grade_question(Q2, AnswerSegment(question_id="Q2", text=TEXT), llm, runs=1, images=[b"img"], mode="hybrid")
    assert llm.image_calls[0][1] == 1 and "<student_answer>" in llm.image_calls[0][0]
    assert g.marks_awarded == 1.5 and g.flags == []


def test_image_only_hides_the_ocr_text_and_skips_quote_checks():
    reply = {"criteria": [dict(REPLY["criteria"][0], evidence="words OCR never saw"), *REPLY["criteria"][1:]]}
    llm = VisionFake([reply])
    g = grade_question(Q2, AnswerSegment(question_id="Q2", text=TEXT), llm, runs=1, images=[b"img"], mode="image")
    assert TEXT not in llm.image_calls[0][0] and g.marks_awarded == 1.5


def test_image_mode_needs_images():
    with pytest.raises(ValueError, match="needs page images"):
        grade_question(Q2, AnswerSegment(question_id="Q2", text=TEXT), VisionFake([REPLY]), runs=1, mode="image")


def test_sheet_falls_back_to_text_without_page_images():
    segs = {"Q2": AnswerSegment(question_id="Q2", text=TEXT)}
    llm = VisionFake([{"criteria": []}] * 0 + [REPLY])
    spec = SPEC.model_copy(update={"questions": [Q2]})
    g = grade_sheet(spec, segs, llm, "s", runs=1, mode="hybrid", pages=[])
    assert llm.image_calls == [] and "no_page_image" in g.questions[0].flags


def test_ablation_runs_image_configs_when_pages_exist(tmp_path):
    page = _page(tmp_path)
    segs = {"Q2": AnswerSegment(question_id="Q2", text=TEXT, pages=[0], lines=[page.lines[1]])}
    spec = SPEC.model_copy(update={"questions": [Q2]})
    llm = VisionFake([REPLY] * 50)
    from autoassess.experiments import Config

    cfgs = [Config("no_review", runs=1, critic=False, advocate=False), Config("image_only", runs=1, critic=False, advocate=False, input_mode="image"),
            Config("hybrid", runs=1, critic=False, advocate=False, input_mode="hybrid")]  # fmt: skip
    res = run_ablation(spec, {"s": segs}, {"A": {("s", "Q2"): 1.5}}, llm, configs=cfgs, pages={"s": [page]})
    assert list(res) == ["no_review", "image_only", "hybrid"] and len(llm.image_calls) == 2
    assert list(run_ablation(spec, {"s": segs}, {"A": {("s", "Q2"): 1.5}}, llm, configs=cfgs)) == ["no_review"]
