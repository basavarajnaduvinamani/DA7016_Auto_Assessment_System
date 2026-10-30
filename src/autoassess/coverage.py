"""Selective auto-marking: what share of answers can skip the teacher, and how good those marks are.

For each confidence threshold an answer is auto-marked when its confidence is at least
the threshold and it carries no review flag (low OCR confidence, possible prompt
injection, inconsistency with the class); everything else goes to the teacher. On the
auto-marked share the table reports QWK, MAE, within-1 and bias against the human
consensus, so a result reads "auto-mark X% of answers at QWK Y".

Inputs are the same as `autoassess evaluate`: a grades folder and a human marks CSV.
Only answers with a human mark are counted.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from autoassess.evaluate import human_consensus
from autoassess.metrics import bootstrap_ci, mean_absolute_error, quadratic_weighted_kappa, signed_bias, within
from autoassess.schemas import ExamSpec, SheetGrade

THRESHOLDS = (0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0)
REVIEW_FLAGS = ("low_ocr_confidence", "possible_prompt_injection", "inconsistent_with:")
HEADLINE = 0.8  # the grader's default review threshold
COLUMNS = ("threshold", "auto_n", "auto_share", "review_n", "qwk", "qwk_ci95", "mae", "within_1", "bias")


def answer_rows(spec: ExamSpec, grades: list[SheetGrade], human: dict) -> list[dict]:
    """One row per human-marked answer: system mark, human consensus, confidence, flagged."""
    consensus = human_consensus(human)
    max_marks = {q.id: q.max_marks for q in spec.questions}
    rows = []
    for g in grades:
        for q in g.questions:
            key = (g.student_id, q.question_id)
            if key not in consensus or q.question_id not in max_marks:
                continue
            rows.append({"student_id": g.student_id, "question_id": q.question_id, "system": q.marks_awarded,
                         "human": consensus[key], "confidence": q.confidence,
                         "flagged": any(f.startswith(REVIEW_FLAGS) for f in q.flags)})
    return rows


def coverage_table(rows: list[dict], thresholds=THRESHOLDS, ci: bool = False) -> list[dict]:
    """Agreement on the auto-marked share at each threshold. Thresholds with too few answers report None."""
    out = []
    for t in thresholds:
        auto = [r for r in rows if r["confidence"] >= t and not r["flagged"]]
        row = {"threshold": t, "auto_n": len(auto), "auto_share": round(len(auto) / len(rows), 3) if rows else None,
               "review_n": len(rows) - len(auto), "qwk": None, "qwk_ci95": None, "mae": None, "within_1": None, "bias": None}
        if auto:
            s, h = [r["system"] for r in auto], [r["human"] for r in auto]
            row.update(qwk=round(quadratic_weighted_kappa(s, h), 3), mae=round(mean_absolute_error(s, h), 3),
                       within_1=round(within(s, h, 1.0), 3), bias=round(signed_bias(s, h), 3))
            if ci and len(auto) >= 5:
                row["qwk_ci95"] = list(bootstrap_ci(s, h, quadratic_weighted_kappa, groups=[r["question_id"] for r in auto]))
        out.append(row)
    return out


def headline(table: list[dict], threshold: float = HEADLINE) -> str | None:
    row = next((r for r in table if abs(r["threshold"] - threshold) < 1e-9), None)
    if not row or row["qwk"] is None:
        return None
    ci = f" {row['qwk_ci95']}" if row["qwk_ci95"] else ""
    return (f"At confidence >= {threshold:g}: auto-mark {row['auto_share']:.0%} of answers "
            f"({row['auto_n']} of {row['auto_n'] + row['review_n']}) at QWK {row['qwk']:.3f}{ci}, "
            f"MAE {row['mae']:.2f}; {row['review_n']} go to the teacher.")


def _cell(value, percent=False) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        return f"[{value[0]:.3f}, {value[1]:.3f}]"
    if percent:
        return f"{value:.0%}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _markdown(table: list[dict], line: str | None, source: str) -> str:
    lines = ["# Coverage: selective auto-marking", "", f"Source: {source}. Answers with a human mark: "
             f"{table[0]['auto_n'] + table[0]['review_n'] if table else 0}.", "",
             "An answer is auto-marked when confidence >= threshold and it has no review flag; agreement is "
             "measured on the auto-marked answers against the human consensus.", ""]
    if line:
        lines += [f"**{line}**", ""]
    lines += ["| Confidence >= | Auto-marked | To teacher | QWK [95% CI] | MAE | Within 1 | Bias |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in table:
        qwk = _cell(r["qwk"]) + (f" {_cell(r['qwk_ci95'])}" if r["qwk_ci95"] else "")
        lines.append(f"| {r['threshold']:g} | {_cell(r['auto_share'], True)} ({r['auto_n']}) | {r['review_n']} | {qwk} | "
                     f"{_cell(r['mae'])} | {_cell(r['within_1'], True)} | {_cell(r['bias'])} |")
    return "\n".join(lines) + "\n"


def _figure(table: list[dict], path: Path) -> bool:
    try:
        from matplotlib.figure import Figure
    except ImportError:
        return False
    points = sorted((r["auto_share"], r["qwk"], r["threshold"]) for r in table if r["qwk"] is not None)
    figure = Figure(figsize=(6, 4))
    ax = figure.subplots()
    ax.plot([p[0] for p in points], [p[1] for p in points], "o-", color="#ad343b")
    for share, qwk, t in points:
        ax.annotate(f"{t:g}", (share, qwk), textcoords="offset points", xytext=(4, 6), fontsize=8, color="#6c727d")
    ax.set(xlabel="Share of answers auto-marked", ylabel="QWK on auto-marked answers", xlim=(0, 1.02),
           title="Selective auto-marking (labels: confidence threshold)")
    ax.grid(alpha=.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    return True


def write_coverage(table: list[dict], out: str | Path, *, source: str = "grades vs human marks") -> dict:
    """Write coverage.json, coverage.csv, coverage.md and, with matplotlib, coverage.png."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    line = headline(table)
    (out / "coverage.json").write_text(json.dumps({"source": source, "headline": line, "rows": table}, indent=2), encoding="utf-8")
    with open(out / "coverage.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in table:
            writer.writerow({**row, "qwk_ci95": " ".join(map(str, row["qwk_ci95"])) if row["qwk_ci95"] else ""})
    (out / "coverage.md").write_text(_markdown(table, line, source), encoding="utf-8")
    figure = out / "coverage.png"
    return {"headline": line, "figure": str(figure) if _figure(table, figure) else None}
