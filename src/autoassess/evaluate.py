"""Compare system marks with human marks.

Human marks come from a CSV with one row per criterion per grader (see
data/sample_exam/human_marks_template.csv). Rows are summed to question
level. With two graders, the human-to-human agreement is reported too, which
is the realistic ceiling for the system.

The report also gives, against the mean of the human graders:
- signed bias overall and per question (negative = the system under-marks),
  with bootstrap 95% intervals;
- the coverage curve: accuracy on the questions accepted automatically at
  each confidence threshold, and the share sent for review;
- results per group (language, handwriting quality, split) from an optional
  sheet metadata CSV, for fairness and for a held-out split;
- the handwriting penalty: marks on the scan minus marks on the typed
  transcript of the same sheet.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from autoassess.confidence import coverage_curve
from autoassess.metrics import agreement_report, signed_bias
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


def load_sheet_meta(path: str | Path) -> dict[str, dict[str, str]]:
    """student_id -> {column: value}, e.g. language, handwriting (good/average/poor), split (dev/test)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["student_id"]: {k: v for k, v in row.items() if k != "student_id"} for row in csv.DictReader(f)}


def human_consensus(human: dict[str, dict[tuple[str, str], float]]) -> dict[tuple[str, str], float]:
    """Mean of the graders who marked each item."""
    sums: dict[tuple[str, str], list[float]] = defaultdict(list)
    for marks in human.values():
        for k, v in marks.items():
            sums[k].append(v)
    return {k: sum(v) / len(v) for k, v in sums.items()}


def compare(
    spec: ExamSpec,
    grades: list[SheetGrade],
    human: dict[str, dict[tuple[str, str], float]],
    meta: dict[str, dict[str, str]] | None = None,
    ci: bool = True,
) -> dict:
    system = {(g.student_id, q.question_id): q.marks_awarded for g in grades for q in g.questions}
    conf = {(g.student_id, q.question_id): q.confidence for g in grades for q in g.questions}
    max_marks = {q.id: q.max_marks for q in spec.questions}
    report: dict = {"per_grader": {}, "human_vs_human": None}

    for grader, marks in human.items():
        keys = sorted(k for k in marks if k in system)
        if not keys:
            continue
        report["per_grader"][grader] = agreement_report(
            [system[k] for k in keys], [marks[k] for k in keys], [max_marks[k[1]] for k in keys], ci=ci,
            groups=[k[1] for k in keys],
        )

    consensus = human_consensus(human)
    keys = sorted(k for k in consensus if k in system)
    if keys:
        sysv, humv, mx = [system[k] for k in keys], [consensus[k] for k in keys], [max_marks[k[1]] for k in keys]
        report["vs_consensus"] = agreement_report(sysv, humv, mx, ci=ci, groups=[k[1] for k in keys])
        report["coverage_curve"] = coverage_curve([conf[k] for k in keys], sysv, humv, mx)
        report["auto_accepted_share"] = round(
            sum(1 for g in grades for q in g.questions if not q.needs_review) / max(1, sum(len(g.questions) for g in grades)), 3
        )
        report["bias_per_question"] = {
            q.id: round(signed_bias([system[k] for k in keys if k[1] == q.id], [consensus[k] for k in keys if k[1] == q.id]), 3)
            for q in spec.questions
            if any(k[1] == q.id for k in keys)
        }
        if meta:
            report["per_group"] = _per_group(keys, system, consensus, max_marks, meta, ci=ci)

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


def _per_group(keys, system, consensus, max_marks, meta, ci=True) -> dict:
    out: dict = {}
    columns = sorted({c for row in meta.values() for c in row})
    for col in columns:
        groups: dict[str, list] = defaultdict(list)
        for k in keys:
            value = (meta.get(k[0]) or {}).get(col, "").strip()
            if value:
                groups[value].append(k)
        out[col] = {
            v: agreement_report([system[k] for k in ks], [consensus[k] for k in ks], [max_marks[k[1]] for k in ks], ci=ci and len(ks) >= 10, groups=[k[1] for k in ks])
            for v, ks in sorted(groups.items())
            if len(ks) >= 2
        }
    return out


def handwriting_penalty(scan: list[SheetGrade], transcript: list[SheetGrade], meta: dict[str, dict[str, str]] | None = None) -> dict:
    """Marks on the scan minus marks on the typed transcript, same sheets and questions.

    Negative means reading the handwriting cost the student marks.
    """
    t = {(g.student_id, q.question_id): q.marks_awarded for g in transcript for q in g.questions}
    rows = [(g.student_id, q.question_id, q.marks_awarded - t[(g.student_id, q.question_id)]) for g in scan for q in g.questions if (g.student_id, q.question_id) in t]
    if not rows:
        return {"n": 0}
    out: dict = {"n": len(rows), "mean_delta": round(sum(d for *_, d in rows) / len(rows), 3)}
    out["sheets_losing_marks"] = sorted({s for s, _, d in rows if d < 0})
    if meta:
        for col in sorted({c for row in meta.values() for c in row}):
            groups: dict[str, list[float]] = defaultdict(list)
            for s, _, d in rows:
                if v := (meta.get(s) or {}).get(col, "").strip():
                    groups[v].append(d)
            out[f"by_{col}"] = {v: round(sum(ds) / len(ds), 3) for v, ds in sorted(groups.items())}
    return out


def write_report(report: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
