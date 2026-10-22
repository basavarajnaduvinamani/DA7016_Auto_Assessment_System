"""Compare system marks with human marks.

Human marks come from a CSV with one row per criterion per grader (see
data/sample_exam/human_marks_template.csv). Rows are summed to question
level. With two graders, the human-to-human agreement is reported too, which
is the realistic ceiling for the system.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from autoassess.metrics import agreement_report
from autoassess.schemas import ExamSpec, SheetGrade


def load_human_marks(path: str | Path) -> dict[str, dict[tuple[str, str], float]]:
    """Return {grader: {(student_id, question_id): marks}}."""
    out: dict[str, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not (row.get("marks_awarded") or "").strip():
                continue
            out[row["grader"]][(row["student_id"], row["question_id"])] += float(row["marks_awarded"])
    return {g: dict(m) for g, m in out.items()}


def load_grades(directory: str | Path) -> list[SheetGrade]:
    return [SheetGrade.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(Path(directory).glob("*.json"))]


def compare(spec: ExamSpec, grades: list[SheetGrade], human: dict[str, dict[tuple[str, str], float]]) -> dict:
    system = {(g.student_id, q.question_id): q.marks_awarded for g in grades for q in g.questions}
    max_marks = {q.id: q.max_marks for q in spec.questions}
    report: dict = {"per_grader": {}, "human_vs_human": None}

    for grader, marks in human.items():
        keys = sorted(k for k in marks if k in system)
        if not keys:
            continue
        report["per_grader"][grader] = agreement_report(
            [system[k] for k in keys], [marks[k] for k in keys], [max_marks[k[1]] for k in keys]
        )

    graders = sorted(human)
    if len(graders) >= 2:
        a, b = human[graders[0]], human[graders[1]]
        keys = sorted(set(a) & set(b))
        if keys:
            report["human_vs_human"] = {
                "graders": graders[:2],
                **agreement_report([a[k] for k in keys], [b[k] for k in keys], [max_marks[k[1]] for k in keys]),
            }

    flagged = [
        {"student_id": g.student_id, "question_id": q.question_id, "flags": q.flags, "confidence": q.confidence}
        for g in grades
        for q in g.questions
        if q.flags and q.flags != ["unanswered"]
    ]
    report["flagged_questions"] = flagged
    return report


def write_report(report: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
