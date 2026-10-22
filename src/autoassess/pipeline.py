"""End-to-end pipeline: answer sheet -> pages -> segments -> grades -> feedback."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from autoassess.baseline import grade_sheet_lexical
from autoassess.feedback import add_feedback
from autoassess.grader import grade_sheet
from autoassess.providers.base import LLMClient, OCRProvider, Translator
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import AnswerSegment, ExamSpec, OCRPage, SheetGrade
from autoassess.segment import segment


@dataclass
class GradingRun:
    spec: ExamSpec
    grade: SheetGrade
    segments: dict[str, AnswerSegment]
    pages: list[OCRPage] = field(default_factory=list)

    def html(self) -> str:
        from autoassess.report import render_html

        return render_html(self.spec, self.grade, self.segments, self.pages)

    def annotate(self, out_dir: str | Path):
        """Write the red-ink marked sheet: a PDF plus one PNG per page."""
        from autoassess.annotate import annotate_sheet

        return annotate_sheet(self.spec, self.grade, self.segments, self.pages, out_dir)


def read_sheet(path: str | Path, ocr: OCRProvider, work_dir: str | Path | None = None, language: str | None = None) -> list[OCRPage]:
    """A .txt sheet is read as text; anything else is ingested and OCR'd page by page."""
    path = Path(path)
    if path.suffix.lower() == ".txt":
        return [PlainTextOCR().read_page(path, 0)]
    from autoassess.ingest import ingest

    work = Path(work_dir or Path(".cache") / "pages" / path.stem)
    return [ocr.read_page(p, i, language) for i, p in enumerate(ingest(path, work))]


def run(
    spec: ExamSpec,
    pages: list[OCRPage],
    student_id: str,
    llm: LLMClient | None,
    *,
    runs: int = 3,
    critic: LLMClient | None = None,
    advocate: LLMClient | None = None,
    second: LLMClient | None = None,
    mode: str = "text",
    feedback: bool = True,
    translator: Translator | None = None,
    feedback_language: str | None = None,
) -> GradingRun:
    """Grade with the LLM grader, or the lexical baseline when llm is None."""
    segments = segment(spec, pages, llm)
    if llm is None:
        grade = grade_sheet_lexical(spec, segments, student_id)
    else:
        grade = grade_sheet(spec, segments, llm, student_id, runs=runs, critic=critic, advocate=advocate, second=second, pages=pages, mode=mode)
    if feedback:
        grade = add_feedback(spec, grade, {k: v.text for k, v in segments.items()}, llm)
        if translator is not None and feedback_language:
            from autoassess.translate import translate_feedback

            grade = translate_feedback(grade, translator, feedback_language)
    return GradingRun(spec, grade, segments, pages)


def grade_pages(spec: ExamSpec, pages: list[OCRPage], student_id: str, llm: LLMClient | None, **kwargs) -> SheetGrade:
    return run(spec, pages, student_id, llm, **kwargs).grade
