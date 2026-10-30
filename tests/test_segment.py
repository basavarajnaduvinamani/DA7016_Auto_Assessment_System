from conftest import SAMPLE, FakeLLM

from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import OCRLine, OCRPage
from autoassess.segment import segment, segment_pages
from autoassess.spec_builder import load_spec

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
    seg = segment_pages(
        SPEC, [_page("Q2. Hallucination is", "1. fluent but false text", "2. caused by training", "Q3 Fine-tuning")]
    )
    assert "1. fluent but false text" in seg["Q2"].text
    assert seg["Q1"].text == ""
    assert seg["Q3"].text == "Fine-tuning"


def test_continuation_across_pages_is_joined():
    pages = [
        _page("Ans 1. Queries keys values", "Ans 2. Hallucination", idx=0),
        _page("Q1 contd: softmax weights", idx=1),
    ]
    seg = segment_pages(SPEC, pages)
    assert seg["Q1"].text == "Queries keys values\ncontd: softmax weights"
    assert seg["Q1"].pages == [0, 1]


def test_llm_fallback_when_no_labels():
    llm = FakeLLM([{"answers": {"Q1": "attention text", "Q2": "", "Q3": "ft text"}}])
    seg = segment(SPEC, [_page("attention text", "ft text")], llm)
    assert seg["Q1"].text == "attention text" and seg["Q3"].text == "ft text"
    assert "<sheet>" in llm.calls[0][1]


def test_comma_after_label():
    seg = segment_pages(SPEC, [_page("1, queries keys", "2, hallucination")])
    assert seg["Q1"].text == "queries keys" and seg["Q2"].text == "hallucination"


def test_llm_resplit_fixes_misread_label_and_is_grounded():
    # OCR read the "2." label as "3.", so the rules put Q2's answer under Q3 and leave Q2 empty.
    pages = [_page("1. queries keys values", "3. fluent but false text", "3. fine-tuning updates weights")]
    assert segment_pages(SPEC, pages)["Q2"].text == ""
    llm = FakeLLM(
        [
            {
                "answers": {
                    "Q1": "queries keys values",
                    "Q2": "fluent but false text and an invented claim",
                    "Q3": "fine-tuning updates weights",
                }
            }
        ]
    )
    seg = segment(SPEC, pages, llm)
    assert seg["Q2"].text == "fluent but false text"  # the invented words are not on the sheet
    assert seg["Q3"].text == "fine-tuning updates weights"
    assert seg["Q2"].lines and seg["Q2"].lines[0].text == "3. fluent but false text"


def test_no_llm_call_when_every_question_found():
    llm = FakeLLM([])
    seg = segment(SPEC, [_page("1. a b", "2. c d", "3. e f")], llm)
    assert seg["Q3"].text == "e f" and not llm.calls
