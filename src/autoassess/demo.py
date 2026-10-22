"""The logic behind the web demo (app.py), kept free of Gradio so it can be tested.

mark_sheet() runs the whole pipeline on one uploaded sheet and returns the
marked pages, the PDF, the HTML report and a comment-first summary.
mark_class() does the same for several sheets with the class report.
A small spend guard caps how many sheets a public demo grades with a paid
LLM per day (AUTOASSESS_DEMO_DAILY_SHEETS, default 40); after that it falls
back to the free lexical baseline and says so.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from autoassess.config import Settings, _env
from autoassess.pipeline import GradingRun, read_sheet, run
from autoassess.providers import make_llm, make_ocr, make_translator
from autoassess.schemas import ExamSpec, SheetGrade

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample_exam"
LANGUAGES = ["English", "Hindi", "Kannada", "Tamil", "Telugu", "Marathi", "Bengali", "Malayalam", "Gujarati", "Odia", "Punjabi"]


@dataclass
class Options:
    use_llm: bool = True
    input_mode: str = "text"  # text | image | hybrid
    two_sided: bool = True  # critic + advocate
    runs: int = 3
    language: str = "English"
    annotate: bool = True


@dataclass
class SheetResult:
    grade: SheetGrade
    summary_md: str
    html_path: Path
    pdf_path: Path | None
    pages: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    run: GradingRun | None = None


def _ocr_for(sheet: Path, settings: Settings):
    """Text sheets need no OCR; for scans prefer Bodhan IndicOCR, then a vision LLM."""
    if sheet.suffix.lower() == ".txt" or settings.ocr_provider != "text":
        return make_ocr(settings), None
    if settings.ocr_key:
        return make_ocr(dataclasses.replace(settings, ocr_provider="bodhan")), "Read with Bodhan IndicOCR."
    if settings.vision_model:
        return make_ocr(dataclasses.replace(settings, ocr_provider="vision")), "Read with a vision model."
    raise ValueError("This sheet is a scan, but no OCR is configured (set BODHAN_OCR_API_KEY or AUTOASSESS_VISION_MODEL).")


class DailyCap:
    """Counts paid gradings per day in the cache folder."""

    def __init__(self, cache_dir: Path, limit: int):
        self.path = cache_dir / "demo_cap.json"
        self.limit = limit

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        return data if data.get("day") == date.today().isoformat() else {"day": date.today().isoformat(), "count": 0}

    def take(self) -> bool:
        data = self._load()
        if data["count"] >= self.limit:
            return False
        data["count"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))
        return True


def summary_markdown(spec: ExamSpec, grade: SheetGrade) -> str:
    """Comments first, numbers after."""
    lines = []
    for q in grade.questions:
        head = f"**{q.question_id}**" + ("  ❓ *a teacher should check this mark*" if q.needs_review else "")
        lines.append(head)
        if q.remark:
            lines += [f"- {line}" for line in q.remark.lines()]
        for e in q.errors:
            lines.append(f'- Check: "{e.quote}" → {e.correction}')
        lines.append(f"- Marks: {q.marks_awarded:g} / {q.max_marks:g}  (confidence {q.confidence:.0%})")
        lines.append("")
    lines.append(f"**Total: {grade.total:g} / {spec.total_marks:g}**")
    if grade.summary_feedback:
        lines.append("")
        lines.append(grade.summary_feedback)
    lines.append("")
    lines.append("*AI-marked. Every mark quotes the student's own words; marks with ❓ go to a teacher.*")
    return "\n".join(lines)


def mark_sheet(spec: ExamSpec, sheet: str | Path, opts: Options, settings: Settings | None = None, out_dir: Path | None = None) -> SheetResult:
    settings = settings or Settings.load()
    sheet = Path(sheet)
    out = out_dir or Path(tempfile.mkdtemp(prefix="autoassess_"))
    notes: list[str] = []
    ocr, note = _ocr_for(sheet, settings)
    if note:
        notes.append(note)
    llm = None
    if opts.use_llm:
        if not settings.llm_api_key and "localhost" not in (settings.llm_base_url or ""):
            notes.append("No LLM key is set, so the free lexical baseline marked this sheet.")
        elif not DailyCap(settings.cache_dir, int(_env("AUTOASSESS_DEMO_DAILY_SHEETS", "40"))).take():
            notes.append("Today's demo limit for the LLM grader is used up, so the free lexical baseline marked this sheet.")
        else:
            llm = make_llm(settings)
    reviewer = make_llm(settings, critic=True) if llm and opts.two_sided else None
    translator = make_translator(settings) if opts.language != "English" and settings.translate_key else None
    if opts.language != "English" and translator is None:
        notes.append("Feedback stays in English: no Bodhan translate key is set.")
    pages = read_sheet(sheet, ocr, work_dir=out / "pages", language=spec.language)
    result = run(
        spec, pages, sheet.stem, llm, runs=opts.runs if llm else 1, critic=reviewer, advocate=reviewer,
        mode=opts.input_mode if llm else "text", translator=translator,
        feedback_language=opts.language if translator else None,
    )  # fmt: skip
    html_path = out / f"{sheet.stem}_report.html"
    html_path.write_text(result.html(), encoding="utf-8")
    pdf, pngs = None, []
    if opts.annotate:
        marked = result.annotate(out / "marked")
        pdf, pngs = marked.pdf, marked.pngs
    return SheetResult(result.grade, summary_markdown(spec, result.grade), html_path, pdf, pngs, notes, result)


def mark_class(spec: ExamSpec, sheets: list[str | Path], opts: Options, settings: Settings | None = None) -> tuple[Path, Path, list[str]]:
    """Grade several sheets, question by question. Returns (class report HTML, zip of marked PDFs and grades, notes)."""
    from autoassess.annotate import annotate_sheet
    from autoassess.classwork import class_report, class_report_html, grade_class
    from autoassess.feedback import add_feedback
    from autoassess.segment import segment

    settings = settings or Settings.load()
    out = Path(tempfile.mkdtemp(prefix="autoassess_class_"))
    notes: list[str] = []
    pages, segs = {}, {}
    llm = make_llm(settings) if opts.use_llm and settings.llm_api_key else None
    if opts.use_llm and llm is None:
        notes.append("No LLM key is set, so the lexical baseline marked these sheets.")
    for s in sheets:
        s = Path(s)
        ocr, _ = _ocr_for(s, settings)
        pages[s.stem] = read_sheet(s, ocr, work_dir=out / "pages" / s.stem, language=spec.language)
        segs[s.stem] = segment(spec, pages[s.stem], llm)
    if llm is not None:
        reviewer = make_llm(settings, critic=True) if opts.two_sided else None
        grades = grade_class(spec, segs, llm, runs=opts.runs, critic=reviewer, advocate=reviewer)
    else:
        from autoassess.baseline import grade_sheet_lexical
        from autoassess.classwork import consistency_pass

        grades = consistency_pass(spec, [grade_sheet_lexical(spec, segs[sid], sid) for sid in segs], segs)
    final = []
    zpath = out / "marked_sheets.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for g in grades:
            g = add_feedback(spec, g, {k: v.text for k, v in segs[g.student_id].items()}, llm)
            final.append(g)
            z.writestr(f"{g.student_id}.json", g.model_dump_json(indent=2))
            if opts.annotate:
                a = annotate_sheet(spec, g, segs[g.student_id], pages[g.student_id], out / "marked" / g.student_id)
                z.write(a.pdf, a.pdf.name)
        report = class_report(spec, final)
        html = class_report_html(report, spec.title)
        z.writestr("class_report.html", html)
        z.writestr("class_report.json", json.dumps(report, indent=2, ensure_ascii=False))
    rpath = out / "class_report.html"
    rpath.write_text(html, encoding="utf-8")
    return rpath, zpath, notes
