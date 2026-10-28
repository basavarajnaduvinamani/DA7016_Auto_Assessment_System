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
from threading import RLock

from autoassess.config import Settings, _env
from autoassess.pipeline import GradingRun, read_sheet, run
from autoassess.providers import make_llm, make_ocr, make_translator
from autoassess.schemas import ExamSpec, OCRPage, SheetGrade

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = Path(__file__).resolve().parent / "sample_exam"
LANGUAGES = [
    "English",
    "Hindi",
    "Kannada",
    "Tamil",
    "Telugu",
    "Marathi",
    "Bengali",
    "Malayalam",
    "Gujarati",
    "Odia",
    "Punjabi",
]


UPLOAD_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".txt")
_CAP_LOCK = RLock()


def demo_settings(settings: Settings | None = None) -> Settings:
    """Resolve demo settings, stripping remote credentials in scripted mode."""
    settings = settings or Settings.load()
    if _env("AUTOASSESS_DEMO_DRY_RUN") == "1" or settings.llm_provider == "fake":
        return dataclasses.replace(
            settings,
            llm_provider="fake",
            llm_base_url="",
            llm_model="fake",
            llm_api_key="",
            bodhan_api_key="",
            bodhan_ocr_api_key="",
            bodhan_translate_api_key="",
            vision_model="",
            ocr_provider="text",
        )
    return settings


def llm_available(settings: Settings) -> bool:
    """A key, the scripted provider, or a keyless local endpoint (Ollama, vLLM)."""
    if settings.llm_provider in ("fake", "custom") and (settings.llm_provider == "fake" or settings.llm_base_url):
        return True
    return bool(settings.llm_api_key)


def health_payload(settings: Settings | None = None) -> dict:
    """Return provider metadata without constructing clients or making calls."""
    settings = demo_settings(settings)
    return {
        "ok": True,
        "llm": settings.llm_provider if llm_available(settings) else "none",
        "ocr": settings.ocr_provider,
    }


def daily_cap(settings: Settings) -> DailyCap:
    """Create the paid-sheet counter using the configured cache and limit."""
    return DailyCap(settings.cache_dir, int(_env("AUTOASSESS_DEMO_DAILY_SHEETS", "40")))


def status_markdown() -> str:
    """Describe provider availability and the remaining daily sheet allowance."""
    settings = demo_settings()
    remaining = daily_cap(settings).remaining()
    if settings.llm_provider == "fake":
        return f"Dry run: scripted text grading, no API calls. Paid LLM sheets remaining today: {remaining}."
    note = (
        "" if llm_available(settings) else "LLM grader disabled: no key configured. The lexical baseline is available. "
    )
    return f"{note}LLM sheets remaining today: {remaining}."


def validate_upload(sheet: str | Path) -> Path:
    """Reject unsupported or excessive uploads before any provider is constructed."""
    sheet = Path(sheet)
    if sheet.suffix.lower() not in UPLOAD_EXTENSIONS:
        raise ValueError("Use a .pdf, .png, .jpg, .jpeg or .txt answer sheet.")
    limit = float(_env("AUTOASSESS_MAX_UPLOAD_MB", "10"))
    if sheet.stat().st_size > limit * 1024 * 1024:
        raise ValueError(f"Upload exceeds the {limit:g} MB limit.")
    if sheet.suffix.lower() == ".pdf":
        import pymupdf

        try:
            with pymupdf.open(sheet) as pdf:
                if pdf.needs_pass:
                    raise ValueError("Password-protected PDFs are not supported.")
                maximum = int(_env("AUTOASSESS_MAX_PAGES", "8"))
                if len(pdf) > maximum:
                    raise ValueError(f"PDF exceeds the {maximum} page limit.")
        except RuntimeError as err:
            raise ValueError("The PDF could not be opened. Upload a valid, unencrypted PDF.") from err
    return sheet


def _provider_note(err: Exception) -> str:
    from autoassess.budget import BudgetExceeded

    reason = (
        "The provider budget is exhausted" if isinstance(err, BudgetExceeded) else "A grading provider is unavailable"
    )
    return f"{reason}; the lexical baseline marked the sheet instead. Feedback is in English."


def _demo_llm(settings: Settings, opts: Options, notes: list[str], count: int = 1):
    if not opts.use_llm:
        return None
    if not llm_available(settings):
        notes.append("No LLM key is set, so the free lexical baseline marked this sheet.")
        return None
    if settings.llm_provider == "fake":
        notes.append("Dry run: scripted grading, not semantic assessment; no API calls.")
    elif not daily_cap(settings).take(count):
        notes.append(
            "Today's demo limit for the LLM grader is used up, so the free lexical baseline marked this sheet."
        )
        return None
    return make_llm(settings)


def _read_demo_sheet(sheet: Path, settings: Settings, out: Path, spec: ExamSpec, notes: list[str]) -> tuple[list, bool]:
    if settings.llm_provider == "fake" and sheet.suffix.lower() != ".txt":
        raise ValueError("Dry-run mode accepts typed .txt sheets. Try the sample sheet.")
    if (
        sheet.suffix.lower() != ".txt"
        and settings.ocr_provider == "text"
        and not (settings.ocr_key or settings.vision_model)
    ):
        raise ValueError(
            "This sheet is a scan, but no OCR is configured (set BODHAN_OCR_API_KEY or AUTOASSESS_VISION_MODEL)."
        )
    try:
        ocr, note = _ocr_for(sheet, settings)
        if note:
            notes.append(note)
        return read_sheet(sheet, ocr, work_dir=out / "pages", language=spec.language), True
    except Exception:
        notes.append(
            "Reading provider unavailable: no answers could be extracted. The baseline report has no assessed answers. Upload a typed .txt sheet to retry."
        )
        return [OCRPage(page_index=0)], False


@dataclass
class Options:
    """Grading, review, annotation and feedback choices for a demo run."""

    use_llm: bool = True
    input_mode: str = "text"  # text | image | hybrid
    # Lower-only audits amplify under-marking; the advocate can recover supported missed credit.
    advocate_review: bool = True
    strict_critic: bool = False
    runs: int = 3
    language: str = "English"
    annotate: bool = True


@dataclass
class SheetResult:
    """A graded sheet with its reports, annotations and provider notices."""

    grade: SheetGrade
    summary_md: str
    html_path: Path
    pdf_path: Path | None
    pages: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    run: GradingRun | None = None


def _ocr_for(sheet: Path, settings: Settings):
    """Text sheets need no OCR; for scans prefer Bodhan IndicOCR, then a vision LLM."""
    if sheet.suffix.lower() == ".txt":
        return make_ocr(dataclasses.replace(settings, ocr_provider="text")), None
    if settings.ocr_provider != "text":
        return make_ocr(settings), None
    if settings.ocr_key:
        return make_ocr(dataclasses.replace(settings, ocr_provider="bodhan")), "Read with Bodhan IndicOCR."
    if settings.vision_model:
        return make_ocr(dataclasses.replace(settings, ocr_provider="vision")), "Read with a vision model."
    raise ValueError(
        "This sheet is a scan, but no OCR is configured (set BODHAN_OCR_API_KEY or AUTOASSESS_VISION_MODEL)."
    )


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
        valid = isinstance(data, dict) and isinstance(data.get("count"), int) and data["count"] >= 0
        return (
            data
            if valid and data.get("day") == date.today().isoformat()
            else {"day": date.today().isoformat(), "count": 0}
        )

    def remaining(self) -> int:
        """Return the number of paid sheet attempts still available today."""
        with _CAP_LOCK:
            return max(0, self.limit - self._load()["count"])

    def take(self, count: int = 1) -> bool:
        """Atomically reserve sheet attempts without exceeding the daily cap."""
        with _CAP_LOCK:
            data = self._load()
            if data["count"] + count > self.limit:
                return False
            data["count"] += count
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


def mark_sheet(
    spec: ExamSpec, sheet: str | Path, opts: Options, settings: Settings | None = None, out_dir: Path | None = None
) -> SheetResult:
    """Read and grade one validated upload, retaining safe fallback notices.

    Args:
        spec: Validated questions, rubric and model answers.
        sheet: Typed answer file or supported scanned document.
        opts: Review, language, input-mode and annotation choices.
        settings: Optional provider/cache settings, resolved from the environment otherwise.
        out_dir: Optional persistent directory; defaults to a new temporary directory.

    Returns:
        Marks, feedback, source segments, reports and any provider fallback notices.
    """
    sheet = validate_upload(sheet)
    settings = demo_settings(settings)
    out = out_dir or Path(tempfile.mkdtemp(prefix="autoassess_"))
    out.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    pages, readable = _read_demo_sheet(sheet, settings, out, spec, notes)
    try:
        llm = _demo_llm(settings, opts, notes) if readable else None
        reviewer = make_llm(settings, critic=True) if llm and (opts.advocate_review or opts.strict_critic) else None
        translator = (
            make_translator(settings) if readable and opts.language != "English" and settings.translate_key else None
        )
        if opts.language != "English" and translator is None:
            notes.append("Feedback stays in English: no Bodhan translate key is set.")
        result = run(
            spec,
            pages,
            sheet.stem,
            llm,
            runs=opts.runs if llm else 1,
            critic=reviewer if opts.strict_critic else None,
            advocate=reviewer if opts.advocate_review else None,
            mode=opts.input_mode if llm else "text",
            translator=translator,
            feedback_language=opts.language if translator else None,
        )
    except Exception as err:
        notes.append(_provider_note(err))
        result = run(spec, pages, sheet.stem, None)
    html_path = out / f"{sheet.stem}_report.html"
    html_path.write_text(result.html(), encoding="utf-8")
    pdf, pngs = None, []
    if opts.annotate:
        marked = result.annotate(out / "marked")
        pdf, pngs = marked.pdf, marked.pngs
    return SheetResult(result.grade, summary_markdown(spec, result.grade), html_path, pdf, pngs, notes, result)


def mark_class(
    spec: ExamSpec, sheets: list[str | Path], opts: Options, settings: Settings | None = None
) -> tuple[Path, Path, list[str]]:
    """Grade several sheets, question by question. Returns (class report HTML, zip of marked PDFs and grades, notes)."""
    from autoassess.annotate import annotate_sheet
    from autoassess.classwork import class_report, class_report_html, grade_class
    from autoassess.feedback import add_feedback
    from autoassess.segment import segment

    sheets = [validate_upload(sheet) for sheet in sheets]
    if not sheets:
        raise ValueError("Upload at least one answer sheet.")
    if len({sheet.stem for sheet in sheets}) != len(sheets):
        raise ValueError("Use a different filename for each sheet in a class.")
    settings = demo_settings(settings)
    out = Path(tempfile.mkdtemp(prefix="autoassess_class_"))
    notes: list[str] = []
    pages = {}
    readable = True
    for sheet in sheets:
        pages[sheet.stem], ok = _read_demo_sheet(sheet, settings, out / sheet.stem, spec, notes)
        readable = readable and ok

    def grade_batch(llm):
        """Grade the loaded class using the selected provider or lexical fallback."""
        segs = {sid: segment(spec, ps, llm) for sid, ps in pages.items()}
        if llm is not None:
            reviewer = make_llm(settings, critic=True) if opts.advocate_review or opts.strict_critic else None
            grades = grade_class(
                spec,
                segs,
                llm,
                runs=opts.runs,
                critic=reviewer if opts.strict_critic else None,
                advocate=reviewer if opts.advocate_review else None,
            )
        else:
            from autoassess.baseline import grade_sheet_lexical
            from autoassess.classwork import consistency_pass

            grades = consistency_pass(spec, [grade_sheet_lexical(spec, segs[sid], sid) for sid in segs], segs)
        return segs, [add_feedback(spec, g, {k: v.text for k, v in segs[g.student_id].items()}, llm) for g in grades]

    try:
        llm = _demo_llm(settings, opts, notes, len(sheets)) if readable else None
        segs, final = grade_batch(llm)
    except Exception as err:
        notes.append(_provider_note(err))
        segs, final = grade_batch(None)
    zpath = out / "marked_sheets.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for g in final:
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
