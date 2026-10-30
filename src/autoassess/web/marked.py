"""Find the red-ink marked page that shows one question, from the saved annotate output."""

from __future__ import annotations

import json
from pathlib import Path

from autoassess.annotate import AnnotationPlan, fmt_marks


def marked_pngs(submission: dict, root: Path) -> list[Path]:
    """The sheet's marked page images that still exist inside the app's files folder."""
    try:
        paths = [Path(p) for p in json.loads(submission.get('artifacts_json') or '{}').get('pngs') or []]
    except (TypeError, ValueError):
        return []
    files = (root / 'files').resolve()
    return paths if paths and all(p.resolve().is_relative_to(files) and p.is_file() for p in paths) else []


def marked_page(submission: dict, root: Path, question, original=None) -> int | None:
    """Index into marked_pngs for the page with this question's circled total, or None when unavailable.

    Marked output is a cover page, the answer pages, then the notes page. The circled
    "marks/max" in the margin locates the question; the saved segment pages are the fallback.
    """
    pngs = marked_pngs(submission, root)
    if not pngs:
        return None
    plans = sorted(pngs[0].parent.glob('*_annotations.json'))
    try:
        plan = AnnotationPlan.model_validate_json(plans[0].read_text(encoding='utf-8')) if plans else None
    except ValueError:
        plan = None
    if plan is None or not plan.pages:
        return 1 if len(pngs) > 1 else 0
    offset = 1 if len(pngs) > len(plan.pages) else 0
    totals = {f"{fmt_marks(q.marks_awarded)}/{fmt_marks(q.max_marks)}" for q in (question, original) if q is not None}
    pages = {m.page for m in plan.marks if m.kind == 'circle' and m.text in totals}
    if len(pages) != 1:
        try:
            segment = json.loads(submission.get('run_json') or '{}')['segments'][question.question_id]
            pages = {segment['pages'][0]} if segment['pages'] else set()
        except (KeyError, TypeError, ValueError):
            pages = set()
    page = min(pages) if len(pages) == 1 and min(pages) < len(plan.pages) else 0
    return min(page + offset, len(pngs) - 1)
