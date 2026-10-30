"""Where the teacher's review time goes on one assignment, from stored grades and decisions only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autoassess.schemas import QuestionGrade, SheetGrade

if TYPE_CHECKING:
    from autoassess.web.store import Store

# grader.grade_question flags an answer for review below this confidence.
THRESHOLD = 0.8
REVIEW_FLAGS = (
    "low_ocr_confidence",
    "possible_prompt_injection",
    "possible_keyword_stuffing",
    "inconsistent_with:",
)


def _flagged(question: QuestionGrade) -> bool:
    return question.needs_review or any(f.startswith(REVIEW_FLAGS) for f in question.flags)


def teacher_time(store: Store, assignment_id: int, threshold: float = THRESHOLD) -> dict[str, Any]:
    """Counts on the original AI marks: auto-accept eligible, flagged, and what the teacher changed."""
    answers = auto = flagged = 0
    teacher_changes = ai_rechecks = 0
    changed_answers: set[tuple[int, str]] = set()
    for submission in store.submissions(assignment_id):
        if not submission["grade_json"]:
            continue
        grade = SheetGrade.model_validate_json(submission["grade_json"])
        for q in grade.questions:
            answers += 1
            if _flagged(q):
                flagged += 1
            elif q.confidence >= threshold:
                auto += 1
        for change in store.changes(submission["id"]):
            if change["kind"] == "ai":
                ai_rechecks += 1
            else:
                teacher_changes += 1
                changed_answers.add((submission["id"], change["question_id"]))

    def share(n: int) -> int | None:
        """Percentage of all answers, or None when nothing is graded yet."""
        return round(100 * n / answers) if answers else None

    return {
        "threshold": threshold,
        "answers": answers,
        "auto": auto,
        "auto_pct": share(auto),
        "flagged": flagged,
        "flagged_pct": share(flagged),
        "other": answers - auto - flagged,
        "overrides": teacher_changes,
        "overridden_answers": len(changed_answers),
        "rechecks": ai_rechecks,
    }
