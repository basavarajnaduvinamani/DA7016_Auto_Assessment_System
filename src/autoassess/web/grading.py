"""Persist the existing demo grader's output and rebuild reviewed artifacts."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autoassess.config import Settings
from autoassess.demo import Options, demo_settings, mark_sheet
from autoassess.pipeline import GradingRun
from autoassess.schemas import AnswerSegment, ExamSpec, OCRPage, SheetGrade

if TYPE_CHECKING:
    from autoassess.web.store import Store


def match_student(filename: str, students: list[dict]) -> int | None:
    """Find a unique roster roll-number token in an uploaded filename."""
    stem = Path(filename).stem
    matches = [
        s for s in students if re.search(r"(?<![A-Za-z0-9])" + re.escape(s["roll_no"]) + r"(?![A-Za-z0-9])", stem, re.I)
    ]
    return matches[0]["id"] if len(matches) == 1 else None


def grade_submission(
    store: Store, submission_id: int, *, settings: Settings | None = None, source: str | Path | None = None
) -> tuple[SheetGrade, str, dict[str, Any]]:
    """Mark one stored upload and return immutable grade, source and artifact records.

    Args:
        store: Repository holding the upload and assignment rubric.
        submission_id: A matched upload with a stable roster roll number.
        settings: Optional provider settings; otherwise use the active demo configuration.
        source: Optional synthetic transcript for offline seed grading.

    Returns:
        The original sheet grade, serialised segments/pages and generated artifact paths.
    """
    submission = store.submission(submission_id)
    assignment = store.assignment(submission["assignment_id"])
    spec = ExamSpec.model_validate_json(assignment["spec_json"])
    out = store.root / "files" / str(assignment["id"]) / f"result-{submission_id}"
    import shutil

    original = Path(source or submission["path"])
    input_dir = out / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / f"{submission['roll_no']}{original.suffix}"
    shutil.copyfile(original, input_path)
    result = mark_sheet(
        spec,
        input_path,
        Options(language=assignment["feedback_language"]),
        settings=settings or demo_settings(),
        out_dir=out,
    )
    if any(note.startswith("Reading provider unavailable:") for note in result.notes):
        raise ValueError("Reading provider unavailable; check OCR setup and retry.")
    if not any(segment.text.strip() for segment in result.run.segments.values()):
        result.notes.append(
            "No recognisable questions were found. All questions are marked unanswered; check the question labels and review the sheet."
        )
    grade = result.grade.model_copy(update={"student_id": submission["roll_no"]})
    run_json = json.dumps(
        {
            "segments": {k: v.model_dump() for k, v in result.run.segments.items()},
            "pages": [p.model_dump() for p in result.run.pages],
            "notes": result.notes,
        },
        ensure_ascii=False,
    )
    artifacts = {
        "pdf": str(result.pdf_path) if result.pdf_path else None,
        "pngs": [str(p) for p in result.pages],
        "html": str(result.html_path),
    }
    return grade, run_json, artifacts


def rebuild_artifacts(store: Store, submission_id: int) -> dict[str, Any]:
    """Regenerate reports from current overrides without another provider call."""
    from autoassess.feedback import add_feedback

    submission = store.submission(submission_id)
    spec = ExamSpec.model_validate_json(store.assignment(submission["assignment_id"])["spec_json"])
    saved = json.loads(submission["run_json"])
    segments = {k: AnswerSegment.model_validate(v) for k, v in saved["segments"].items()}
    pages = [OCRPage.model_validate(p) for p in saved["pages"]]
    grade = store.effective_grade(submission)
    # Reconcile rubric feedback with current marks without another provider call.
    grade = add_feedback(spec, grade, {k: v.text for k, v in segments.items()}, None)
    run = GradingRun(spec, grade, segments, pages)
    out = store.root / "files" / str(submission["assignment_id"]) / f"reviewed-{submission_id}"
    annotated = run.annotate(out)
    html_path = out / "report.html"
    html_path.write_text(run.html(), encoding="utf-8")
    artifacts = {"pdf": str(annotated.pdf), "pngs": [str(p) for p in annotated.pngs], "html": str(html_path)}
    store.set_artifacts(submission_id, artifacts)
    return artifacts


def fake_settings() -> Settings:
    """Build credential-free settings for deterministic synthetic seed grading."""
    settings = demo_settings()
    return dataclasses.replace(
        settings,
        llm_provider="fake",
        llm_api_key="",
        llm_base_url="",
        llm_model="fake",
        ocr_provider="text",
        bodhan_api_key="",
        bodhan_ocr_api_key="",
        bodhan_translate_api_key="",
        vision_model="",
    )
