"""Marking the class, not just the sheet.

Teachers mark Q1 for the whole pile before Q2, so they hold one standard per
question. grade_class() does the same:

- question by question across all sheets;
- answers that are the same once spacing, case and punctuation are ignored
  are graded once and get identical marks;
- a consistency pass then compares similar answers to the same question and
  flags pairs that are close in wording but far apart in marks, sending both
  for review ("inconsistent_with:<student>");
- class_report() summarises each question: mean and spread, a histogram,
  the rubric criteria most students missed, and the most common mistakes,
  each with an example in a student's own words, so the teacher knows what
  to reteach.
"""

from __future__ import annotations

import html
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable

from autoassess.grader import dependency_context, grade_question
from autoassess.providers.base import LLMClient
from autoassess.schemas import AnswerSegment, ExamSpec, QuestionGrade, SheetGrade

_WORD = re.compile(r"\w+")


def _canon(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _vector(text: str) -> Counter:
    words = _WORD.findall(text.lower())
    return Counter(words + [f"{a}_{b}" for a, b in zip(words, words[1:])])


def cosine(a: str, b: str) -> float:
    va, vb = _vector(a), _vector(b)
    dot = sum(v * vb[k] for k, v in va.items() if k in vb)
    na, nb = math.sqrt(sum(v * v for v in va.values())), math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def grade_class(
    spec: ExamSpec,
    sheets: dict[str, dict[str, AnswerSegment]],
    llm: LLMClient,
    *,
    images: Callable[[str, AnswerSegment], list[bytes] | None] | None = None,
    mode: str = "text",
    similar: float = 0.85,
    gap: float = 0.25,
    **kwargs,
) -> list[SheetGrade]:
    """Grade every sheet question by question, then run the consistency pass."""
    by_sheet: dict[str, dict[str, QuestionGrade]] = defaultdict(dict)
    for q in spec.questions:
        done: dict[str, QuestionGrade] = {}  # canonical answer text -> grade
        for sid, segs in sheets.items():
            seg = segs.get(q.id) or AnswerSegment(question_id=q.id, text="")
            key = _canon(seg.text)
            if key and key in done and mode == "text":
                by_sheet[sid][q.id] = done[key].model_copy(update={"flags": [*done[key].flags, "same_as_earlier_answer"]})
                continue
            crops = images(sid, seg) if images and mode != "text" else None
            g = grade_question(
                q, seg, llm, context=dependency_context(q, segs), images=crops, mode=mode if crops else "text", **kwargs
            )
            by_sheet[sid][q.id] = g
            if key:
                done[key] = g
    grades = [
        SheetGrade(exam_id=spec.exam_id, student_id=sid, questions=[by_sheet[sid][q.id] for q in spec.questions])
        for sid in sheets
    ]
    return consistency_pass(spec, grades, sheets, similar=similar, gap=gap)


def consistency_pass(
    spec: ExamSpec,
    grades: list[SheetGrade],
    sheets: dict[str, dict[str, AnswerSegment]],
    *,
    similar: float = 0.85,
    gap: float = 0.25,
) -> list[SheetGrade]:
    """Flag similar answers whose marks differ by more than `gap` of the question's marks."""
    flags: dict[tuple[str, str], list[str]] = defaultdict(list)
    for q in spec.questions:
        rows = [
            (g.student_id, (sheets.get(g.student_id, {}).get(q.id) or AnswerSegment(question_id=q.id, text="")).text, qg)
            for g in grades
            for qg in g.questions
            if qg.question_id == q.id
        ]
        rows = [r for r in rows if r[1].strip()]
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                (sa, ta, ga), (sb, tb, gb) = rows[i], rows[j]
                if abs(ga.marks_awarded - gb.marks_awarded) <= gap * q.max_marks + 1e-9:
                    continue
                if cosine(ta, tb) >= similar:
                    flags[(sa, q.id)].append(f"inconsistent_with:{sb}")
                    flags[(sb, q.id)].append(f"inconsistent_with:{sa}")
    out = []
    for g in grades:
        qs = []
        for qg in g.questions:
            extra = flags.get((g.student_id, qg.question_id))
            if extra:
                qg = qg.model_copy(update={"flags": [*qg.flags, *extra], "needs_review": True})
            qs.append(qg)
        out.append(g.model_copy(update={"questions": qs}))
    return out


# ---------------------------------------------------------------------------
# Class report
# ---------------------------------------------------------------------------


def _histogram(values: list[float], max_marks: float, bins: int = 5) -> list[int]:
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int(v / max_marks * bins))] += 1
    return counts


def class_report(spec: ExamSpec, grades: list[SheetGrade], top: int = 3) -> dict:
    report: dict = {"exam_id": spec.exam_id, "students": len(grades), "questions": {}}
    totals = [g.total for g in grades]
    if totals:
        report["total"] = {
            "mean": round(sum(totals) / len(totals), 2),
            "min": min(totals),
            "max": max(totals),
            "max_marks": spec.total_marks,
            "histogram": _histogram(totals, spec.total_marks),
        }
    for q in spec.questions:
        qgs = [(g.student_id, qg) for g in grades for qg in g.questions if qg.question_id == q.id]
        marks = [qg.marks_awarded for _, qg in qgs]
        if not marks:
            continue
        crit = {c.id: c for c in q.criteria}
        missed = Counter()
        example_reason: dict[str, str] = {}
        for _, qg in qgs:
            if "unanswered" in qg.flags:
                continue
            for r in qg.criteria:
                if r.marks_awarded < crit[r.criterion_id].marks:
                    missed[r.criterion_id] += 1
                    example_reason.setdefault(r.criterion_id, r.reason)
        mistakes: dict[str, dict] = {}
        for sid, qg in qgs:
            for e in qg.errors:
                key = _canon(e.correction or e.quote)
                m = mistakes.setdefault(key, {"correction": e.correction, "example": e.quote, "student": sid, "count": 0})
                m["count"] += 1
        answered = sum(1 for _, qg in qgs if "unanswered" not in qg.flags)
        report["questions"][q.id] = {
            "max_marks": q.max_marks,
            "mean": round(sum(marks) / len(marks), 2),
            "full_marks_share": round(sum(m >= q.max_marks for m in marks) / len(marks), 3),
            "unanswered": len(marks) - answered,
            "histogram": _histogram(marks, q.max_marks),
            "most_missed": [
                {"criterion_id": cid, "criterion": crit[cid].description, "missed_by": n, "share": round(n / max(1, answered), 3), "example_reason": example_reason[cid]}
                for cid, n in missed.most_common(top)
            ],
            "common_mistakes": sorted(mistakes.values(), key=lambda m: -m["count"])[:top],
            "for_review": [sid for sid, qg in qgs if qg.needs_review],
        }
    return report


def class_report_html(report: dict, title: str = "") -> str:
    esc = html.escape
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>Class report: {esc(title or report['exam_id'])}</title><style>",
        "body{font:15px/1.55 system-ui,sans-serif;max-width:960px;margin:0 auto;padding:24px 16px;color:#1d1d1f}"
        "h2{margin-top:32px}.bar{display:inline-block;background:#c41c2c;height:12px;vertical-align:middle;border-radius:2px}"
        "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}"
        ".quiet{color:#666}@media(prefers-color-scheme:dark){body{background:#121212;color:#e8eaed}td,th{border-color:#3c4043}.quiet{color:#9aa0a6}}",
        "</style></head><body>",
        f"<h1>Class report</h1><p class=quiet>{esc(title or report['exam_id'])} &middot; {report['students']} students</p>",
    ]
    if t := report.get("total"):
        parts.append(f"<p>Mean total {t['mean']:g} of {t['max_marks']:g} (range {t['min']:g} to {t['max']:g}).</p>")
    for qid, q in report["questions"].items():
        blank = f" &middot; {q['unanswered']} unanswered" if q["unanswered"] else ""
        parts.append(f"<h2>{esc(qid)}</h2><p>Mean {q['mean']:g} of {q['max_marks']:g} &middot; full marks {q['full_marks_share']:.0%}{blank}</p>")
        hist = q["histogram"]
        width = max(hist) or 1
        step = q["max_marks"] / len(hist)
        parts.append("<table>" + "".join(
            f"<tr><td class=quiet>{i * step:g}&ndash;{(i + 1) * step:g}</td><td><span class=bar style='width:{n / width * 240:.0f}px'></span> {n}</td></tr>"
            for i, n in enumerate(hist)
        ) + "</table>")  # fmt: skip
        if q["most_missed"]:
            parts.append("<p><strong>Most missed rubric points</strong></p><ul>" + "".join(
                f"<li>{esc(m['criterion'])} <span class=quiet>(missed by {m['missed_by']}, {m['share']:.0%})</span></li>" for m in q["most_missed"]
            ) + "</ul>")  # fmt: skip
        if q["common_mistakes"]:
            parts.append("<p><strong>Common mistakes</strong></p><ul>" + "".join(
                f"<li>&ldquo;{esc(m['example'])}&rdquo; &rarr; {esc(m['correction'])} <span class=quiet>({m['count']} students)</span></li>"
                for m in q["common_mistakes"]
            ) + "</ul>")  # fmt: skip
        if q["for_review"]:
            parts.append(f"<p class=quiet>For review: {esc(', '.join(q['for_review']))}</p>")
    parts.append("</body></html>")
    return "".join(parts)
