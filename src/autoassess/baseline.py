"""Lexical baseline grader: no LLM, word overlap with each criterion.

It is deliberately simple. It gives the evaluation a floor to beat, and lets
the pipeline run end to end with no model at all.
"""

from __future__ import annotations

import re

from autoassess.schemas import AnswerSegment, CriterionResult, ExamSpec, Question, QuestionGrade, SheetGrade, Verdict

_STOP = set(
    """a an the of to in on for and or but is are was were be been being as at by with from that this these those
    it its into than then so such any some each every one two three at least e g eg says states state mentions
    gives give explains explain answer student valid example examples like how what when why which who whom
    there their them they he she we you your our has have had do does did not no can could should would may
    might must will shall""".split()
)


def _stem(w: str) -> str:
    return w[:6]


def _content_words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in _STOP}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def grade_question_lexical(question: Question, segment: AnswerSegment) -> QuestionGrade:
    answer = segment.text.strip()
    answer_words = _content_words(answer)
    sentences = _sentences(answer)
    results = []
    for c in question.criteria:
        target = _content_words(c.description)
        coverage = len(target & answer_words) / len(target) if target else 0.0
        if c.allow_partial:
            marks = round(c.marks * min(1.0, coverage / 0.6) * 4) / 4
        else:
            marks = c.marks if coverage >= 0.5 else 0.0
        marks = min(marks, c.marks)
        best = max(sentences, key=lambda s: len(_content_words(s) & target), default=None)
        verdict = Verdict.MET if marks >= c.marks else Verdict.PARTIAL if marks > 0 else Verdict.NOT_MET
        results.append(
            CriterionResult(
                criterion_id=c.id,
                verdict=verdict,
                marks_awarded=marks,
                evidence=best if marks > 0 else None,
                reason=f"{coverage:.0%} of the criterion's key words appear in the answer.",
            )
        )
    total = min(sum(r.marks_awarded for r in results), question.max_marks)
    return QuestionGrade(
        question_id=question.id,
        marks_awarded=total,
        max_marks=question.max_marks,
        criteria=results,
        flags=[] if answer else ["unanswered"],
    )


def grade_sheet_lexical(spec: ExamSpec, segments: dict[str, AnswerSegment], student_id: str) -> SheetGrade:
    return SheetGrade(
        exam_id=spec.exam_id,
        student_id=student_id,
        questions=[
            grade_question_lexical(q, segments.get(q.id) or AnswerSegment(question_id=q.id, text=""))
            for q in spec.questions
        ],
    )
