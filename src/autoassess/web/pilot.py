"""Pilot log export: review minutes per sheet, override rate and calibration shift, with no student text.

One CSV, one row per assignment and one summary row per teacher (``level`` says which).
Every number comes from stored marks, the decision log and review-time events. Nothing
from a sheet is exported: no names, roll numbers, answers, feedback or reasons; teachers
appear as ``T<id>`` and assignments by id.

Definitions:
- review minutes: time from opening an answer to the first accept or change, summed; gaps
  over 15 minutes are left out (see ``teacher_time.review_activity``);
- minutes per sheet: review minutes divided by sheets with at least one decided answer;
- override rate: share of decided answers whose decision was a mark change;
- calibration shift: mean of (teacher's mark minus AI's mark) over changed criteria.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any

from autoassess.schemas import SheetGrade
from autoassess.web.teacher_time import THRESHOLD, _flagged, calibration, review_activity

if TYPE_CHECKING:
    from autoassess.web.store import Store

COLUMNS = [
    "level",
    "teacher_ref",
    "assignment_id",
    "class_id",
    "is_demo",
    "feedback_language",
    "released",
    "sheets_graded",
    "sheets_reviewed",
    "answers_marked",
    "answers_decided",
    "auto_accept_eligible_pct",
    "flagged_pct",
    "review_minutes",
    "minutes_per_sheet",
    "median_seconds_per_answer",
    "override_rate_pct",
    "teacher_mark_changes",
    "ai_rechecks",
    "calibration_n",
    "calibration_shift",
    "calibration_direction",
]


def _assignment_stats(store: Store, assignment: dict[str, Any]) -> tuple[dict[str, Any], list[dict], list[float]]:
    """One assignment's row plus its raw events and mark deltas, for pooling per teacher."""
    sheets = answers = auto = flagged = changes = rechecks = 0
    deltas: list[float] = []
    for submission in store.submissions(assignment["id"]):
        if not submission["grade_json"]:
            continue
        sheets += 1
        for q in SheetGrade.model_validate_json(submission["grade_json"]).questions:
            answers += 1
            flagged += _flagged(q)
            auto += not _flagged(q) and q.confidence >= THRESHOLD
        for change in store.changes(submission["id"]):
            if change["kind"] == "ai":
                rechecks += 1
            else:
                changes += 1
                deltas.append(change["new_marks"] - change["old_marks"])
    events = store.review_events(assignment["id"])
    row = {
        "level": "assignment",
        "assignment_id": assignment["id"],
        "class_id": assignment["class_id"],
        "is_demo": int(bool(assignment["is_demo"])),
        "feedback_language": assignment.get("feedback_language", "English"),
        "released": int(bool(assignment["released"])),
        "sheets_graded": sheets,
        "answers_marked": answers,
        "auto_accept_eligible_pct": round(100 * auto / answers) if answers else None,
        "flagged_pct": round(100 * flagged / answers) if answers else None,
        "teacher_mark_changes": changes,
        "ai_rechecks": rechecks,
        **_activity(events),
        **_calibration(deltas),
    }
    return row, events, deltas


def _activity(events: list[dict]) -> dict[str, Any]:
    activity = review_activity(events)
    reviewed = len({e["submission_id"] for e in events if e["kind"] in ("accept", "override")})
    minutes = activity["review_minutes"]
    return {
        "sheets_reviewed": reviewed,
        "answers_decided": activity["decided"],
        "review_minutes": minutes,
        "minutes_per_sheet": round(minutes / reviewed, 2) if minutes is not None and reviewed else None,
        "median_seconds_per_answer": activity["median_review_seconds"],
        "override_rate_pct": activity["override_rate_pct"],
    }


def _calibration(deltas: list[float]) -> dict[str, Any]:
    result = calibration(deltas)
    return {
        "calibration_n": result["calibration_n"],
        "calibration_shift": result["calibration_shift"],
        "calibration_direction": result["calibration_direction"],
    }


def teacher_rows(store: Store, teacher_id: int) -> list[dict[str, Any]]:
    """A teacher's summary row first (pilot assignments only, demo ones left out), then one row per assignment."""
    ref = f"T{teacher_id}"
    stats = [
        _assignment_stats(store, assignment)
        for classroom in store.classes(teacher_id)
        for assignment in store.assignments(classroom["id"])
    ]
    rows = [{"teacher_ref": ref, **row} for row, _, _ in stats]
    pilot = [(row, events, deltas) for row, events, deltas in stats if not row["is_demo"]]

    def total(key: str) -> int:
        """Sum one column over the pilot (non-demo) assignments."""
        return sum(row[key] or 0 for row, _, _ in pilot)

    def weighted(key: str) -> int | None:
        """Average a percentage column, weighted by answers marked."""
        answers = total("answers_marked")
        return round(sum((row[key] or 0) * row["answers_marked"] for row, _, _ in pilot) / answers) if answers else None

    summary = {
        "level": "teacher",
        "teacher_ref": ref,
        "assignment_id": "",
        "class_id": "",
        "is_demo": 0,
        "feedback_language": "",
        "released": total("released"),
        "sheets_graded": total("sheets_graded"),
        "answers_marked": total("answers_marked"),
        "auto_accept_eligible_pct": weighted("auto_accept_eligible_pct"),
        "flagged_pct": weighted("flagged_pct"),
        "teacher_mark_changes": total("teacher_mark_changes"),
        "ai_rechecks": total("ai_rechecks"),
        **_activity([e for _, events, _ in pilot for e in events]),
        **_calibration([d for _, _, deltas in pilot for d in deltas]),
    }
    return [summary, *rows]


def all_rows(store: Store, *, include_demo: bool = False) -> list[dict[str, Any]]:
    """Rows for every teacher (the demo teacher only when asked)."""
    from autoassess.web.login import DEMO_EMAIL

    with store.connect() as db:
        teachers = [dict(r) for r in db.execute("SELECT id, email FROM teachers ORDER BY id")]
    rows = []
    for teacher in teachers:
        if teacher["email"].lower() == DEMO_EMAIL and not include_demo:
            continue
        rows += teacher_rows(store, teacher["id"])
    return rows


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    """CSV bytes with a fixed column order; empty cells for values that don't apply yet."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in COLUMNS})
    return out.getvalue().encode("utf-8")
