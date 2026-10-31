"""Where the teacher's review time goes on one assignment, from stored grades and decisions only."""

from __future__ import annotations

import statistics
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
    deltas: list[float] = []  # teacher's new mark minus the AI's, per changed criterion
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
                deltas.append(change["new_marks"] - change["old_marks"])

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
        **calibration(deltas),
        **review_activity(store.review_events(assignment_id)),
    }


# Fewer changes than this say little about a teacher's habits, so no direction is reported.
MIN_CHANGES = 5


def calibration(deltas: list[float]) -> dict[str, Any]:
    """How the teacher's changed marks compare with the AI's: the average shift and its direction.

    Read-only: it describes the teacher's habit and never changes a mark.
    """
    if not deltas:
        return {"calibration_n": 0, "calibration_shift": None, "calibration_direction": None}
    shift = round(statistics.fmean(deltas), 2)
    direction = None
    if len(deltas) >= MIN_CHANGES:
        direction = "more generous" if shift >= 0.25 else "stricter" if shift <= -0.25 else "in line"
    return {"calibration_n": len(deltas), "calibration_shift": shift, "calibration_direction": direction}


# A gap longer than this between opening an answer and deciding it is treated as the teacher stepping away.
IDLE_SECONDS = 15 * 60


def review_activity(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Override rate and time per decided answer, from logged open/accept/override events.

    An answer counts as decided at its first accept or override. Its review time runs from the
    latest open before that decision; gaps over ``IDLE_SECONDS`` are left out rather than counted.
    """
    last_open: dict[tuple[int, str], float] = {}
    decided: dict[tuple[int, str], str] = {}
    seconds: list[float] = []
    for event in events:
        key = (event["submission_id"], event["question_id"])
        if event["kind"] == "open":
            last_open[key] = event["at"]
        elif key not in decided:
            decided[key] = event["kind"]
            if key in last_open and 0 <= event["at"] - last_open[key] <= IDLE_SECONDS:
                seconds.append(event["at"] - last_open[key])
        elif event["kind"] == "override":
            decided[key] = "override"
    overridden = sum(kind == "override" for kind in decided.values())
    return {
        "decided": len(decided),
        "override_rate_pct": round(100 * overridden / len(decided)) if decided else None,
        "median_review_seconds": round(statistics.median(seconds)) if seconds else None,
        "review_minutes": round(sum(seconds) / 60, 1) if seconds else None,
    }
