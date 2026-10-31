"""Red-ink annotation: planning marks from a grade, and rendering them."""

from conftest import SAMPLE
from PIL import Image

from autoassess.annotate import annotate_sheet, fmt_marks, locate, plan_annotations, typeset
from autoassess.cli import main
from autoassess.pipeline import read_sheet, run
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import BBox, ErrorMark, OCRLine, Remark
from autoassess.segment import segment_pages
from autoassess.spec_builder import load_spec

SPEC = load_spec(SAMPLE / "exam_spec.yaml")


def _graded(sid="S001"):
    pages = read_sheet(SAMPLE / "answer_sheets" / f"{sid}.txt", PlainTextOCR())
    return run(SPEC, pages, sid, None)


def test_fmt_marks():
    assert [fmt_marks(x) for x in (3, 2.5, 0.25, 0.75, 1.75, 1.3)] == ["3", "2½", "¼", "¾", "1¾", "1.3"]


def test_locate_finds_the_line_where_a_long_quote_ends():
    lines = [(0, OCRLine(text="The output is the weighted", bbox=BBox(x0=0, y0=0, x1=100, y1=10))),
             (0, OCRLine(text="sum of the value vectors.", bbox=BBox(x0=0, y0=20, x1=100, y1=30)))]  # fmt: skip
    assert locate("the weighted sum of the value vectors", lines).line.text.startswith("sum")
    assert locate("the weighted sum of the value vectors", lines, tail=False).line.text.startswith("The output")
    hit = locate("weighted", lines)
    assert hit.line.text.startswith("The output") and 0.5 < hit.start < hit.end <= 1.0
    assert locate("nothing like this at all", lines) is None


def test_plan_has_one_tick_per_whole_mark_and_examiner_symbols(tmp_path):
    r = _graded()
    g = r.grade
    g.questions[1].errors = [ErrorMark(quote="training only teaches the model", correction="rewards plausible text")]
    g.questions[2].needs_review = True
    g.questions[2].criteria[4].tags = ["ecf"]
    pages = typeset(r.pages, tmp_path, "S001")
    plan = plan_annotations(SPEC, g, segment_pages(SPEC, pages), pages)
    ticks = sum(1 for m in plan.marks if m.kind == "tick")
    assert ticks == sum(int(c.marks_awarded) for q in g.questions for c in q.criteria)
    texts = [m.text for m in plan.marks if m.kind == "text"]
    assert "(4½)" in texts and "ECF" in texts and "rewards plausible text" in texts
    assert [m.text for m in plan.marks if m.kind == "circle"] == ["4½/5", "1¾/4", "5/6"]
    assert sum(1 for m in plan.marks if m.kind == "question") == 1 and plan.review == ["Q3"]
    assert sum(1 for m in plan.marks if m.kind == "wavy") == 1
    assert texts.count("Good!") <= 2
    assert plan.cover[2] == ("Q3", "5 ?") and plan.total == "11¼ / 15"


def test_marks_stay_left_of_the_margin_and_praise_is_once_per_answer(tmp_path):
    from autoassess.annotate import PAGE_W, RIGHT_MARGIN

    for sid in ("S001", "S002"):
        r = _graded(sid)
        pages = typeset(r.pages, tmp_path / sid, sid)
        plan = plan_annotations(SPEC, r.grade, segment_pages(SPEC, pages), pages)
        rule = PAGE_W - RIGHT_MARGIN + 10  # the right margin's red rule
        ticks = [m for m in plan.marks if m.kind == "tick"]
        assert ticks and all(m.x + m.w <= rule for m in ticks)
        praise = [m for m in plan.marks if m.text == "Good!"]
        assert len(praise) <= 2 and len({round(m.y) for m in praise}) == len(praise)


def test_no_praise_on_a_weak_answer(tmp_path):
    r = _graded("S003")
    pages = typeset(r.pages, tmp_path, "S003")
    plan = plan_annotations(SPEC, r.grade, segment_pages(SPEC, pages), pages)
    assert "Good!" not in [m.text for m in plan.marks]


def test_annotate_sheet_writes_cover_pages_notes_and_pdf(tmp_path):
    r = _graded()
    r.grade.questions[0].remark = Remark(
        strength="clear softmax step", fix="", next_step="say why we scale by sqrt(d_k)"
    )
    a = annotate_sheet(SPEC, r.grade, r.segments, r.pages, tmp_path)
    assert a.pdf.exists() and a.pdf.read_bytes()[:4] == b"%PDF"
    assert len(a.pngs) >= 3  # cover, at least one answer page, notes
    assert Image.open(a.pngs[0]).size == (1240, 1754)
    assert (tmp_path / "S001_annotations.json").exists()
    assert any("Well done: clear softmax step" in n for n in a.plan.notes)


def test_scanned_page_with_boxes_is_annotated_in_place(tmp_path):
    img = tmp_path / "scan.png"
    Image.new("RGB", (1000, 1400), "white").save(img)
    from autoassess.schemas import OCRPage

    page = OCRPage(page_index=0, image_path=str(img), lines=[
        OCRLine(text="Ans 2 Hallucination is confident text that is not true.", bbox=BBox(x0=80, y0=200, x1=760, y1=240)),
    ])  # fmt: skip
    r = run(SPEC, [page], "S9", None)
    a = annotate_sheet(SPEC, r.grade, r.segments, [page], tmp_path, cover=False, notes=False)
    assert len(a.pngs) == 1 and Image.open(a.pngs[0]).size == (1000, 1400)
    assert a.plan.pages == [str(img)]  # not re-typeset


def test_cli_grade_annotate(tmp_path, capsys):
    sheet = str(SAMPLE / "answer_sheets" / "S002.txt")
    assert (
        main(
            [
                "grade",
                "--spec",
                str(SAMPLE / "exam_spec.yaml"),
                "--out",
                str(tmp_path),
                "--baseline",
                "--annotate",
                sheet,
            ]
        )
        == 0
    )
    assert (tmp_path / "marked" / "S002_marked.pdf").exists()
    assert "marked sheet:" in capsys.readouterr().out
