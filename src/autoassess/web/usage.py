"""What marking has cost a teacher so far, per assignment and in total, at measured average rates."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from autoassess.schemas import SheetGrade
from autoassess.web.teacher_time import review_activity

if TYPE_CHECKING:
    from autoassess.web.store import Store

# Measured rates, the same ones the README's "Cost per sheet" table uses (docs/report/numbers.md#cost).
USD_PER_ANSWER = 0.006  # full pipeline on gemini-2.5-flash via OpenRouter; an upper bound for advocate-only
INR_PER_USD = 88.0
INR_PER_SCANNED_PAGE = 0.20  # Bodhan IndicOCR
INR_PER_10K_TRANSLATED_TOKENS = 0.20  # Bodhan Indic-Translate
TRANSLATED_TOKENS_PER_ANSWER = 200  # a few sentences of feedback per answer

RATES = [
    ("Marking, per answer", f"${USD_PER_ANSWER:g} ≈ ₹{USD_PER_ANSWER * INR_PER_USD:.2f}"),
    ("Reading a handwritten or scanned page", f"₹{INR_PER_SCANNED_PAGE:.2f}"),
    ("Feedback translation, per 10k tokens", f"₹{INR_PER_10K_TRANSLATED_TOKENS:.2f}"),
    ("Re-opening a marked sheet or exporting", "free"),
]


def _sheet_counts(submission: dict[str, Any]) -> tuple[int, int]:
    """Answers marked and scanned pages read for one graded submission."""
    grade = SheetGrade.model_validate_json(submission["grade_json"])
    pages = json.loads(submission["run_json"] or "{}").get("pages", [])
    scanned = sum(page.get("provider", "text") not in ("", "text") for page in pages)
    return len(grade.questions), scanned


def assignment_usage(store: Store, assignment: dict[str, Any]) -> dict[str, Any]:
    """Sheets, answers, pages, estimated rupee cost and teacher review time for one assignment."""
    sheets = answers = pages = rechecks = 0
    for submission in store.submissions(assignment["id"]):
        if not submission["grade_json"]:
            continue
        sheets += 1
        n_answers, n_pages = _sheet_counts(submission)
        answers += n_answers
        pages += n_pages
        rechecks += sum(change["kind"] == "ai" for change in store.changes(submission["id"]))
    translated = assignment.get("feedback_language", "English") != "English"
    marking = (answers + rechecks) * USD_PER_ANSWER * INR_PER_USD
    reading = pages * INR_PER_SCANNED_PAGE
    translation = answers * TRANSLATED_TOKENS_PER_ANSWER / 10_000 * INR_PER_10K_TRANSLATED_TOKENS if translated else 0.0
    activity = review_activity(store.review_events(assignment["id"]))
    total = marking + reading + translation
    return {
        "id": assignment["id"],
        "title": assignment["title"],
        "language": assignment.get("feedback_language", "English"),
        "sheets": sheets,
        "answers": answers,
        "pages": pages,
        "rechecks": rechecks,
        "marking_inr": marking,
        "reading_inr": reading,
        "translation_inr": translation,
        "total_inr": total,
        "per_sheet_inr": total / sheets if sheets else None,
        "decided": activity["decided"],
        "review_minutes": activity["review_minutes"] or 0.0,
    }


def usage(store: Store, teacher_id: int) -> dict[str, Any]:
    """Every class the teacher owns, with per-assignment usage rows and workspace totals."""
    classes = []
    for classroom in store.classes(teacher_id):
        rows = [assignment_usage(store, a) for a in store.assignments(classroom["id"])]
        classes.append({"id": classroom["id"], "name": classroom["name"], "assignments": rows})
    rows = [row for c in classes for row in c["assignments"]]
    total = sum(row["total_inr"] for row in rows)
    sheets = sum(row["sheets"] for row in rows)
    return {
        "classes": classes,
        "rates": RATES,
        "total_inr": total,
        "total_usd": total / INR_PER_USD,
        "sheets": sheets,
        "answers": sum(row["answers"] for row in rows),
        "pages": sum(row["pages"] for row in rows),
        "per_sheet_inr": total / sheets if sheets else None,
        "decided": sum(row["decided"] for row in rows),
        "review_minutes": round(sum(row["review_minutes"] for row in rows), 1),
    }
