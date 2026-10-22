from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import OCRLine, OCRPage
from autoassess.segment import segment, segment_pages
from autoassess.spec_builder import load_spec
from conftest import SAMPLE, FakeLLM

SPEC = load_spec(SAMPLE / "exam_spec.yaml")


def _sheet(name):
    return [PlainTextOCR().read_page(SAMPLE / "answer_sheets" / name, 0)]


def test_out_of_order_answers():
    seg = segment_pages(SPEC, _sheet("S002.txt"))
    assert seg["Q1"].text.startswith("Attention lets")
    assert seg["Q2"].text == "Hallucination is when the model makes things up."
    assert seg["Q3"].text.startswith("Fine tuning means")


def test_missing_answer_is_empty():
    seg = segment_pages(SPEC, _sheet("S003.txt"))
    assert seg["Q1"].text.startswith("Attention is the most")
    assert seg["Q3"].text == ""


def _page(*lines, idx=0):
    return OCRPage(page_index=idx, lines=[OCRLine(text=t) for t in lines])


def test_numbered_list_inside_answer_does_not_jump_back():
    seg = segment_pages(SPEC, [_page("Q2. Hallucination is", "1. fluent but false text", "2. caused by training", "Q3 Fine-tuning")])
    assert "1. fluent but false text" in seg["Q2"].text
    assert seg["Q1"].text == ""
    assert seg["Q3"].text == "Fine-tuning"


def test_continuation_across_pages_is_joined():
    pages = [_page("Ans 1. Queries keys values", "Ans 2. Hallucination", idx=0), _page("Q1 contd: softmax weights", idx=1)]
    seg = segment_pages(SPEC, pages)
    assert seg["Q1"].text == "Queries keys values\ncontd: softmax weights"
    assert seg["Q1"].pages == [0, 1]


def test_llm_fallback_when_no_labels():
    llm = FakeLLM([{"answers": {"Q1": "attention text", "Q2": "", "Q3": "ft text"}}])
    seg = segment(SPEC, [_page("attention text", "ft text")], llm)
    assert seg["Q1"].text == "attention text" and seg["Q3"].text == "ft text"
    assert "<sheet>" in llm.calls[0][1]
