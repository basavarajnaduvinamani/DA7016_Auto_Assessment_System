from autoassess.feedback import add_feedback, question_feedback, verify_items
from autoassess.pipeline import run
from autoassess.providers.base import Translator
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.report import find_span, render_html
from autoassess.schemas import CriterionResult, QuestionGrade, Verdict
from autoassess.spec_builder import load_spec
from autoassess.translate import translate_feedback
from conftest import SAMPLE, FakeLLM

SPEC = load_spec(SAMPLE / "exam_spec.yaml")
Q2 = SPEC.question("Q2")
ANSWER = "Hallucination is when the model writes confident text that is not true."


def _grade():
    return QuestionGrade(question_id="Q2", marks_awarded=1.5, max_marks=4, criteria=[
        CriterionResult(criterion_id="Q2.c1", verdict=Verdict.MET, marks_awarded=1.5, evidence="confident text that is not true", reason="defined"),
        CriterionResult(criterion_id="Q2.c2", verdict=Verdict.NOT_MET, marks_awarded=0, reason="no cause given"),
        CriterionResult(criterion_id="Q2.c3", verdict=Verdict.NOT_MET, marks_awarded=0, reason="no mitigation"),
    ])


def test_verifier_drops_unsupported_items():
    raw = {
        "earned": [
            {"criterion_id": "Q2.c1", "text": 'You defined it well: "confident text that is not true".'},
            {"criterion_id": "Q2.c2", "text": "Great cause."},  # praise without marks
            {"criterion_id": "Q9.c1", "text": "Unknown."},
        ],
        "lost": [
            {"criterion_id": "Q2.c2", "text": "No cause.", "next_step": "Explain that next-token training rewards plausible text."},
            {"criterion_id": "Q2.c3", "text": 'You wrote "use RAG".', "next_step": "Name a mitigation."},  # misquote
            {"criterion_id": "Q2.c1", "text": "Lost here?", "next_step": "x"},  # full marks, nothing lost
        ],
    }
    items, flags = verify_items(Q2, _grade(), ANSWER, raw)
    assert [(i.kind, i.criterion_id) for i in items] == [("earned", "Q2.c1"), ("lost", "Q2.c2")]
    assert sorted(flags) == sorted([
        "feedback_dropped:praise_without_marks:Q2.c2",
        "feedback_dropped:unknown_criterion:Q9.c1",
        "feedback_dropped:misquote:Q2.c3",
        "feedback_dropped:loss_without_deduction:Q2.c1",
    ])


def test_every_lost_criterion_gets_a_next_step():
    raw = {"earned": [], "lost": [{"criterion_id": "Q2.c2", "text": "No cause.", "next_step": "Explain next-token training."}]}
    fb = question_feedback(Q2, _grade(), ANSWER, FakeLLM([raw]))
    lost = [i for i in fb.items if i.kind == "lost"]
    assert [i.criterion_id for i in lost] == ["Q2.c2", "Q2.c3"]
    assert all(i.next_step for i in lost)
    assert "Where marks were lost:" in fb.render()


def test_rubric_feedback_without_llm():
    fb = question_feedback(Q2, _grade(), ANSWER)
    assert [(i.kind, i.criterion_id) for i in fb.items] == [("earned", "Q2.c1"), ("lost", "Q2.c2"), ("lost", "Q2.c3")]
    assert fb.items[1].next_step.startswith("Make sure your answer gives one valid cause")


def test_unanswered_feedback():
    fb = question_feedback(Q2, _grade(), "")
    assert "No answer was found" in fb.summary


def _sample_run(sid="S002"):
    pages = [PlainTextOCR().read_page(SAMPLE / "answer_sheets" / f"{sid}.txt", 0)]
    return run(SPEC, pages, sid, None)


def test_pipeline_fills_feedback_and_summary():
    r = _sample_run("S003")
    assert r.grade.summary_feedback.startswith("Total: ")
    assert "Not attempted: Q3." in r.grade.summary_feedback
    assert all(q.feedback for q in r.grade.questions)


def test_find_span_ignores_case_and_punctuation():
    text = "It uses Query, Key and VALUE vectors."
    s, e = find_span("query key and value", text)
    assert text[s:e] == "Query, Key and VALUE"
    assert find_span("not here", text) is None


def test_report_highlights_evidence_and_escapes_html():
    r = _sample_run("S001")
    seg = r.segments["Q1"]
    seg.text += " <script>alert(1)</script>"
    html = render_html(SPEC, r.grade, r.segments, r.pages)
    assert "<mark" in html and "<script>" not in html and "&lt;script&gt;" in html
    assert "Where marks were lost" in html or "What earned marks" in html


def test_report_outlines_evidence_on_page_image(tmp_path):
    from PIL import Image

    from autoassess.schemas import BBox, OCRLine, OCRPage
    from autoassess.segment import segment_pages

    img = tmp_path / "page_000.png"
    Image.new("RGB", (400, 300), "white").save(img)
    page = OCRPage(page_index=0, image_path=str(img), lines=[
        OCRLine(text="Ans 2. Hallucination is when the model writes confident text that is not true.", bbox=BBox(x0=10, y0=20, x1=390, y1=60))])
    segs = segment_pages(SPEC, [page])
    from autoassess.grader import grade_sheet
    from autoassess.schemas import SheetGrade
    grade = SheetGrade(exam_id="e", student_id="s", questions=[
        _grade() if q.id == "Q2" else QuestionGrade(question_id=q.id, marks_awarded=0, max_marks=q.max_marks, criteria=[
            CriterionResult(criterion_id=c.id, verdict=Verdict.NOT_MET, marks_awarded=0, reason="") for c in q.criteria])
        for q in SPEC.questions])
    html = render_html(SPEC, grade, segs, [page])
    assert '<rect x="10.0" y="20.0"' in html and "data:image/png;base64," in html


class Upper(Translator):
    def translate(self, text, target_language, source_language="English"):
        return f"[{target_language}] {text}"


def test_translate_feedback_keeps_english_and_evidence():
    g = add_feedback(SPEC, _sample_run("S001").grade, {}, None)
    t = translate_feedback(g, Upper(), "Hindi")
    q = t.questions[0]
    assert q.feedback.startswith("[Hindi] ") and q.feedback_en == g.questions[0].feedback
    assert q.criteria[0].evidence == g.questions[0].criteria[0].evidence
    assert t.feedback_language == "Hindi" and t.summary_feedback.startswith("[Hindi]")
