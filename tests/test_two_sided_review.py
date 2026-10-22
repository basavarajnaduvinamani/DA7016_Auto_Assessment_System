"""Advocate, second examiner, confidence, follow-through, privacy, lint and the new metrics."""

import pytest

from autoassess.confidence import combine_signals, coverage_curve
from autoassess.evaluate import compare, handwriting_penalty, human_consensus
from autoassess.feedback import question_feedback, verify_remark
from autoassess.grader import build_prompt, dependency_context, evidence_in_answer, grade_question, grade_sheet
from autoassess.metrics import bootstrap_ci, mean_absolute_error, signed_bias
from autoassess.privacy import PrivacyError, anonymise, check_provider_for_real_sheets
from autoassess.schemas import AnswerSegment, CriterionResult, ExamSpec, OCRLine, OCRPage, QuestionGrade, SheetGrade, Verdict
from autoassess.segment import segment_pages, strip_crossed_out
from autoassess.spec_builder import lint_spec, load_spec
from conftest import SAMPLE, FakeLLM

SPEC = load_spec(SAMPLE / "exam_spec.yaml")
Q2 = SPEC.question("Q2")
ANSWER = (
    "Hallucination is when the model writes confident text that is not true. It happens because training "
    "rewards likely tokens. We can look things up in documents before answering."
)


def _reply(c3=(0, None)):
    return {"criteria": [
        {"criterion_id": "Q2.c1", "marks_awarded": 1.5, "evidence": "confident text that is not true", "reason": "r1"},
        {"criterion_id": "Q2.c2", "marks_awarded": 1.25, "evidence": "training rewards likely tokens", "reason": "r2"},
        {"criterion_id": "Q2.c3", "marks_awarded": c3[0], "evidence": c3[1], "reason": "no mitigation named"},
    ]}  # fmt: skip


def seg(text=ANSWER, lines=()):
    return AnswerSegment(question_id="Q2", text=text, lines=list(lines))


# --- quotes -----------------------------------------------------------------


def test_fuzzy_quote_tolerates_one_ocr_slip_but_not_a_different_sentence():
    text = "The model stores the rnemory of past tokens in a cache."
    assert not evidence_in_answer("stores the memory of past tokens", text)
    assert evidence_in_answer("stores the memory of past tokens", text, fuzzy=0.9)
    assert not evidence_in_answer("deletes all of the old tokens", text, fuzzy=0.9)
    assert not evidence_in_answer("memory", text, fuzzy=0.9)  # too short to match loosely


def test_fuzzy_quote_is_tagged_not_withdrawn():
    reply = _reply()
    reply["criteria"][0]["evidence"] = "confident text that is not ture"
    g = grade_question(Q2, seg(), FakeLLM([reply]), runs=1)
    assert g.criteria[0].marks_awarded == 1.5 and "fuzzy_quote" in g.criteria[0].tags


# --- advocate ---------------------------------------------------------------


def test_advocate_raises_only_with_a_verified_quote():
    advocate = FakeLLM([{"proposals": [
        {"criterion_id": "Q2.c3", "decision": "raise", "marks": 1.0, "evidence": "look things up in documents before answering", "reason": "that is retrieval"},
    ]}])  # fmt: skip
    g = grade_question(Q2, seg(), FakeLLM([_reply()]), runs=1, advocate=advocate)
    assert g.criteria[2].marks_awarded == 1.0 and "advocate" in g.criteria[2].tags
    assert "advocate_raised:Q2.c3" in g.flags and g.marks_awarded == 3.75
    assert "CRITERIA BELOW FULL MARKS" in advocate.calls[0][1] and "Q2.c1" not in advocate.calls[0][1].split("BELOW FULL MARKS")[1]
    assert g.confidence_signals["review_agreement"] == pytest.approx(0.75)


def test_advocate_without_quote_changes_nothing():
    advocate = FakeLLM([{"proposals": [{"criterion_id": "Q2.c3", "decision": "raise", "marks": 1.25, "evidence": "uses RAG", "reason": "x"}]}])
    g = grade_question(Q2, seg(), FakeLLM([_reply()]), runs=1, advocate=advocate)
    assert g.criteria[2].marks_awarded == 0 and "advocate_unsupported:Q2.c3" in g.flags


def test_advocate_marks_benefit_of_the_doubt_when_runs_disagreed():
    runs = [_reply(), _reply(c3=(0.5, "look things up in documents")), _reply()]
    advocate = FakeLLM([{"proposals": [{"criterion_id": "Q2.c3", "decision": "raise", "marks": 0.75, "evidence": "look things up in documents", "reason": "x"}]}])
    g = grade_question(Q2, seg(), FakeLLM(runs), runs=3, advocate=advocate)
    assert {"advocate", "bod"} <= set(g.criteria[2].tags)


def test_advocate_is_skipped_at_full_marks():
    full = _reply(c3=(1.25, "look things up in documents before answering"))
    advocate = FakeLLM([])
    grade_question(Q2, seg(), FakeLLM([full]), runs=1, advocate=advocate)
    assert advocate.calls == []


# --- second examiner and confidence -----------------------------------------


def test_second_examiner_disagreement_lowers_confidence_and_flags_review():
    second = FakeLLM([{"criteria": [
        {"criterion_id": "Q2.c1", "marks_awarded": 0, "evidence": None, "reason": "x"},
        {"criterion_id": "Q2.c2", "marks_awarded": 0, "evidence": None, "reason": "x"},
        {"criterion_id": "Q2.c3", "marks_awarded": 0, "evidence": None, "reason": "x"},
    ]}])  # fmt: skip
    g = grade_question(Q2, seg(), FakeLLM([_reply()]), runs=1, second=second)
    assert g.confidence_signals["model_agreement"] == pytest.approx(1 - 2.75 / 4, abs=1e-3)
    assert g.confidence == pytest.approx(0.312) and g.needs_review and "examiners_disagree" in g.flags
    assert g.marks_awarded == 2.75  # the second examiner informs confidence, it doesn't change marks


def test_agreeing_examiners_are_auto_accepted():
    g = grade_question(Q2, seg(), FakeLLM([_reply()]), runs=1, second=FakeLLM([_reply()]))
    assert g.confidence == 1.0 and not g.needs_review


def test_low_ocr_confidence_sends_for_review():
    lines = [OCRLine(text=ANSWER, confidence=0.5)]
    g = grade_question(Q2, seg(lines=lines), FakeLLM([_reply()]), runs=1)
    assert g.needs_review and g.confidence_signals["ocr"] == 0.5


def test_combine_signals_takes_the_weakest():
    assert combine_signals({}) == 1.0
    assert combine_signals({"a": 0.9, "b": 0.6}) == 0.6


def test_coverage_curve_trades_coverage_for_accuracy():
    conf = [0.95, 0.9, 0.5, 0.4]
    system, human, mx = [2, 3, 0, 4], [2, 3, 3, 1], [4, 4, 4, 4]
    rows = {r["threshold"]: r for r in coverage_curve(conf, system, human, mx, thresholds=(0.0, 0.8))}
    assert rows[0.0]["coverage"] == 1.0 and rows[0.0]["mae"] == 1.5
    assert rows[0.8]["coverage"] == 0.5 and rows[0.8]["mae"] == 0 and rows[0.8]["bias"] == 0


# --- follow-through ---------------------------------------------------------


def _ecf_spec():
    return ExamSpec.model_validate({
        "exam_id": "ecf", "title": "t", "questions": [
            {"id": "Q1", "text": "Compute 6 x 7.", "max_marks": 1, "criteria": [{"id": "Q1.c1", "description": "Gets 42 for the product", "marks": 1}]},
            {"id": "Q2", "text": "Double your answer to Q1.", "max_marks": 1, "depends_on": ["Q1"],
             "criteria": [{"id": "Q2.c1", "description": "Doubles the Q1 result correctly", "marks": 1, "follow_through": True}]},
        ]})  # fmt: skip


def test_follow_through_sees_earlier_answer_and_tags_ecf():
    spec = _ecf_spec()
    segs = {"Q1": AnswerSegment(question_id="Q1", text="6 x 7 = 40"), "Q2": AnswerSegment(question_id="Q2", text="2 x 40 = 80")}
    assert dependency_context(spec.question("Q2"), segs) == "Q1: 6 x 7 = 40"
    llm = FakeLLM([
        {"criteria": [{"criterion_id": "Q1.c1", "marks_awarded": 0, "evidence": None, "reason": "wrong"}]},
        {"criteria": [{"criterion_id": "Q2.c1", "marks_awarded": 1, "evidence": "2 x 40 = 80", "reason": "doubles 40", "follow_through": True}]},
    ])  # fmt: skip
    g = grade_sheet(spec, segs, llm, "s", runs=1)
    assert "EARLIER ANSWERS" in llm.calls[1][1] and "6 x 7 = 40" in llm.calls[1][1]
    assert "EARLIER ANSWERS" not in llm.calls[0][1]
    assert g.questions[1].criteria[0].tags == ["ecf"]


def test_ecf_tag_needs_a_follow_through_criterion():
    r = _reply()
    r["criteria"][0]["follow_through"] = True
    g = grade_question(Q2, seg(), FakeLLM([r]), runs=1)
    assert g.criteria[0].tags == []
    assert "follow-through" not in build_prompt(Q2, ANSWER)


def test_unknown_dependency_is_rejected():
    with pytest.raises(ValueError, match="depends_on"):
        ExamSpec.model_validate({"exam_id": "x", "title": "t", "questions": [
            {"id": "Q1", "text": "t", "max_marks": 1, "depends_on": ["Q9"], "criteria": [{"id": "c", "description": "d", "marks": 1}]}]})  # fmt: skip


# --- crossed-out work and privacy -------------------------------------------


def test_crossed_out_work_is_ignored():
    assert strip_crossed_out("A stack is ~~FIFO~~ LIFO") == "A stack is LIFO"
    assert strip_crossed_out("[crossed out: wrong formula] E = mc^2") == "E = mc^2"
    page = OCRPage(page_index=0, lines=[OCRLine(text="Ans 2 ~~wrong idea~~"), OCRLine(text="~~all struck~~"), OCRLine(text="right idea")])
    assert segment_pages(SPEC, [page])["Q2"].text == "right idea"


def test_anonymise_removes_identity_but_keeps_answer_text():
    text = "Name: Asha Rao\nRoll No: 1RV22CS045\nEmail asha@example.com, phone 9876543210\nAns 1 attention uses softmax"
    out = anonymise(text)
    for leaked in ("Asha", "1RV22CS045", "asha@example.com", "9876543210"):
        assert leaked not in out
    assert "Ans 1 attention uses softmax" in out


def test_real_sheets_never_go_to_the_free_tier():
    gemini = "https://generativelanguage.googleapis.com/v1beta/openai"
    with pytest.raises(PrivacyError):
        check_provider_for_real_sheets(gemini, real_sheets=True)
    check_provider_for_real_sheets(gemini, real_sheets=True, paid_gemini=True)
    check_provider_for_real_sheets("https://openrouter.ai/api/v1", real_sheets=True)
    check_provider_for_real_sheets(gemini, real_sheets=False)


# --- rubric lint ------------------------------------------------------------


def test_lint_flags_bundled_and_orphan_follow_through():
    spec = ExamSpec.model_validate({"exam_id": "x", "title": "t", "questions": [
        {"id": "Q1", "text": "t", "max_marks": 2, "model_answer": "m", "criteria": [
            {"id": "Q1.c1", "description": "Defines the term and gives an example and explains why; also cites a source", "marks": 1},
            {"id": "Q1.c2", "description": "Uses the earlier result to compute the area", "marks": 1, "follow_through": True}]}]})  # fmt: skip
    w = "\n".join(lint_spec(spec))
    assert "Q1.c1: bundles several checks" in w and "Q1.c2: follow-through but Q1 has no depends_on" in w


# --- feedback remark --------------------------------------------------------


def _qgrade(marks=(1.5, 1.25, 0)):
    ev = ["confident text that is not true", "training rewards likely tokens", None]
    crit = [
        CriterionResult(criterion_id=f"Q2.c{i + 1}", verdict=Verdict.MET if m else Verdict.NOT_MET, marks_awarded=m, evidence=ev[i] if m else None, reason="r")
        for i, m in enumerate(marks)
    ]
    return QuestionGrade(question_id="Q2", marks_awarded=sum(marks), max_marks=4, criteria=crit)


def test_remark_drops_person_praise_misquotes_and_long_parts():
    raw = {"remark": {"strength": "You are brilliant.", "fix": 'You wrote "use RAG" but never explained it.', "next_step": "Name one mitigation and say how it reduces false answers."}}
    remark, flags = verify_remark(_qgrade(), ANSWER, raw)
    assert remark.next_step.startswith("Name one mitigation") and not remark.strength and not remark.fix
    assert sorted(flags) == ["remark_dropped:about_the_person:strength", "remark_dropped:misquote:fix"]


def test_feedback_puts_comments_before_the_marks_and_fills_the_remark():
    fb = question_feedback(Q2, _qgrade(), ANSWER)
    assert fb.remark.strength and fb.remark.fix.startswith("give one valid mitigation")
    lines = fb.render().splitlines()
    assert lines[0].startswith("Well done:") and lines[-1] == "2.75 of 4 marks."


def test_full_marks_get_a_stretch_question_not_a_fix():
    fb = question_feedback(Q2, _qgrade((1.5, 1.25, 1.25)), ANSWER)
    assert fb.remark.fix == "" and fb.remark.next_step.startswith("Explain why")


# --- metrics and evaluation -------------------------------------------------


def test_signed_bias_and_bootstrap_interval():
    system, human = [1, 2, 3, 4, 5, 2, 3], [2, 3, 3, 5, 5, 3, 4]
    assert signed_bias(system, human) == pytest.approx(-5 / 7)
    lo, hi = bootstrap_ci(system, human, mean_absolute_error, n_boot=500)
    assert lo <= mean_absolute_error(system, human) <= hi


def _sheet(sid, marks, conf=1.0):
    return SheetGrade(exam_id="x", student_id=sid, questions=[
        QuestionGrade(question_id="Q2", marks_awarded=marks, max_marks=4, criteria=[], confidence=conf, needs_review=conf < 0.8)])  # fmt: skip


def test_compare_reports_bias_coverage_and_groups():
    grades = [_sheet("a", 2), _sheet("b", 1, conf=0.3), _sheet("c", 3)]
    human = {"A": {("a", "Q2"): 3, ("b", "Q2"): 3, ("c", "Q2"): 3}, "B": {("a", "Q2"): 2, ("b", "Q2"): 4, ("c", "Q2"): 3}}
    assert human_consensus(human)[("a", "Q2")] == 2.5
    meta = {"a": {"language": "kn"}, "b": {"language": "kn"}, "c": {"language": "en"}}
    rep = compare(SPEC, grades, human, meta)
    assert rep["vs_consensus"]["bias"] == pytest.approx((-0.5 - 2.5 + 0) / 3, abs=1e-3)
    assert rep["bias_per_question"]["Q2"] < 0 and rep["auto_accepted_share"] == pytest.approx(0.667)
    assert "kn" in rep["per_group"]["language"]
    auto = next(r for r in rep["coverage_curve"] if r["threshold"] == 0.8)
    assert auto["coverage"] == pytest.approx(0.667) and auto["mae"] == 0.25


def test_handwriting_penalty():
    scan, typed = [_sheet("a", 2), _sheet("b", 3)], [_sheet("a", 3), _sheet("b", 3)]
    out = handwriting_penalty(scan, typed, {"a": {"handwriting": "poor"}, "b": {"handwriting": "good"}})
    assert out["mean_delta"] == -0.5 and out["sheets_losing_marks"] == ["a"]
    assert out["by_handwriting"] == {"good": 0.0, "poor": -1.0}



def test_lenient_marking_policy_reaches_every_prompt():
    from autoassess.advocate import build_advocate_prompt
    from autoassess.critic import build_critic_prompt

    data = SPEC.model_dump()
    data["marking"] = "lenient"
    for q in data["questions"]:
        q["marking"] = None  # inherit the exam's policy
    data["questions"][1]["marking"] = "standard"  # a question can opt out
    spec = ExamSpec.model_validate(data)
    q1, q2 = spec.questions[0], spec.questions[1]
    r = [CriterionResult(criterion_id=c.id, verdict=Verdict.PARTIAL, marks_awarded=0.5, evidence="x", reason="") for c in q1.criteria]
    for prompt in (build_prompt(q1, "ans"), build_critic_prompt(q1, "ans", r), build_advocate_prompt(q1, "ans", r)):
        assert "MARKING POLICY: lenient" in prompt
    assert "MARKING POLICY" not in build_prompt(q2, "ans")
    assert "MARKING POLICY" not in build_prompt(SPEC.questions[0], "ans")  # standard is the default
    with pytest.raises(ValueError):
        ExamSpec.model_validate({**SPEC.model_dump(), "marking": "generous"})
