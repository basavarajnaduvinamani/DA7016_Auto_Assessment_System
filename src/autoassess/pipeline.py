"""End-to-end pipeline: answer sheet file -> pages -> segments -> grades."""

from __future__ import annotations

from pathlib import Path

from autoassess.baseline import grade_sheet_lexical
from autoassess.grader import grade_sheet
from autoassess.providers.base import LLMClient, OCRProvider
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import ExamSpec, OCRPage, SheetGrade
from autoassess.segment import segment


def read_sheet(path: str | Path, ocr: OCRProvider, work_dir: str | Path | None = None, language: str | None = None) -> list[OCRPage]:
    """A .txt sheet is read as text; anything else is ingested and OCR'd page by page."""
    path = Path(path)
    if path.suffix.lower() == ".txt":
        return [PlainTextOCR().read_page(path, 0)]
    from autoassess.ingest import ingest

    work = Path(work_dir or Path(".cache") / "pages" / path.stem)
    return [ocr.read_page(p, i, language) for i, p in enumerate(ingest(path, work))]


def grade_pages(
    spec: ExamSpec,
    pages: list[OCRPage],
    student_id: str,
    llm: LLMClient | None,
    *,
    runs: int = 3,
    critic: LLMClient | None = None,
) -> SheetGrade:
    """Grade with the LLM grader, or the lexical baseline when llm is None."""
    segments = segment(spec, pages, llm)
    if llm is None:
        return grade_sheet_lexical(spec, segments, student_id)
    return grade_sheet(spec, segments, llm, student_id, runs=runs, critic=critic)
