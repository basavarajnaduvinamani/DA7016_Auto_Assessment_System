"""Red-ink annotation: write the marking back onto the answer sheet.

Marks follow what Indian examiners write on answer booklets, and each one
comes from something the grader decided, so none of it is decoration:

- one tick per mark awarded, at the end of the line that holds the evidence
  (a half mark is written as a small fraction after the ticks);
- "ECF" beside follow-through credit and "BOD" beside benefit of the doubt;
- a wavy underline under a wrong statement, with a short correction;
- a caret "^" at the end of an answer that is missing a point, with the fix;
- sub-part marks in brackets in the right margin, the question total circled
  in the left margin, and a "?" beside any mark sent for human review;
- a short margin remark: one strength, one fix, one thing for next time;
- "Good!" after the ticks of a strong answer: once per answer, twice per sheet at most;
- a cover page with the marks grid filled in, and an "AI-marked" stamp, so
  the handwriting style never passes for a human examiner;
- a last page with the full feedback, comments before marks.

plan_annotations() turns a graded sheet into an AnnotationPlan (plain JSON,
easy to test and to re-render), and render_plan() draws it in a handwriting
font, kept straight and level so the marks read cleanly. A .txt sheet, or OCR without line boxes, is first
typeset onto ruled pages so every mark has a place to go.
"""

from __future__ import annotations

import math
import re
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from autoassess.schemas import AnswerSegment, BBox, ExamSpec, OCRLine, OCRPage, QuestionGrade, SheetGrade

FONT_DIR = Path(__file__).parent / "fonts"
INK = (196, 28, 44)
STUDENT_INK = (28, 42, 92)
VERSION = "autoassess v0.2"

MarkKind = Literal["tick", "text", "wavy", "caret", "circle", "question"]


class Mark(BaseModel):
    """A drawable annotation with page coordinates, text and mark value."""

    kind: MarkKind
    page: int
    x: float
    y: float
    w: float = 0
    h: float = 0
    text: str = ""
    size: float = 34


class AnnotationPlan(BaseModel):
    """The marks and feedback to draw over a student's pages."""

    student_id: str
    pages: list[str] = Field(description="Page image paths, in order.")
    marks: list[Mark] = Field(default_factory=list)
    cover: list[tuple[str, str]] = Field(default_factory=list, description="(question, marks) rows for the cover grid.")
    total: str = ""
    confidence: float = 1.0
    review: list[str] = Field(default_factory=list, description="Questions marked '?'.")
    notes: list[str] = Field(default_factory=list, description="Lines for the examiner's notes page.")


def fmt_marks(x: float) -> str:
    """2.5 -> '2½', 0.25 -> '¼', 3.0 -> '3'."""
    whole, frac = int(x), round(x - int(x), 2)
    sym = {0.25: "¼", 0.5: "½", 0.75: "¾"}.get(frac)
    if frac == 0:
        return str(whole)
    if sym:
        return f"{whole or ''}{sym}"
    return f"{x:g}"


# ---------------------------------------------------------------------------
# Typesetting sheets that have no page images or no line boxes
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = 1240, 1754  # A4 at 150 dpi
LEFT, RIGHT_MARGIN, TOP, LINE_H = 150, 330, 120, 60
TICK_GUTTER = 130  # space kept free between the written text and the margin rule for ticks


# Indian scripts the red ink and typed sheets can draw, as (Unicode block, ink font, plain font).
# Kalam (handwriting) covers Latin and Devanagari; the Noto Sans fonts carry Latin too, so a line
# that mixes English terms with one Indian script renders with a single font.
SCRIPT_FONTS = [
    (r"[\u0900-\u097F]", "Kalam", "NotoSansDevanagari.ttf"),  # Devanagari (Hindi, Marathi)
    (r"[\u0C80-\u0CFF]", "BalooTamma2.ttf", "NotoSansKannada.ttf"),  # Kannada
    (r"[\u0B80-\u0BFF]", "NotoSansTamil.ttf", "NotoSansTamil.ttf"),  # Tamil
    (r"[\u0C00-\u0C7F]", "NotoSansTelugu.ttf", "NotoSansTelugu.ttf"),  # Telugu
]


def _script_font(text: str, ink: bool) -> str | None:
    """The font file for the first Indian script found in ``text``; None for Latin-only text."""
    for pattern, ink_font, plain_font in SCRIPT_FONTS:
        if re.search(pattern, text):
            return ink_font if ink else plain_font
    return None


def _font(size: int, bold: bool = False, script_text: str = ""):
    """Red-ink handwriting font (Kalam), switching to a font that has the glyphs of ``script_text``."""
    from PIL import ImageFont

    name = _script_font(script_text, ink=True)
    if name is None or name == "Kalam":
        name = "Kalam-Bold.ttf" if bold else "Kalam-Regular.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _student_font(size: int = 30, script_text: str = ""):
    """Plain font for typeset student text; Pillow's default unless the text needs an Indian script."""
    from PIL import ImageFont

    name = _script_font(script_text, ink=False)
    if name is not None:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _wrap_to_width(text: str, max_px: float, size: int = 30) -> list[str]:
    """Wrap ``text`` so every line fits ``max_px`` in the font it will be drawn with (Indian scripts run wider)."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _student_font(size, text)
    chars = int(max_px / 15.5)
    while chars > 10:
        parts = textwrap.wrap(text, width=chars)
        if all(draw.textlength(part, font=font) <= max_px for part in parts):
            return parts
        chars -= 4
    return textwrap.wrap(text, width=max(chars, 10))


def typeset(pages: list[OCRPage], out_dir: Path, student_id: str) -> list[OCRPage]:
    """Lay the sheet's text out on ruled A4 pages and return pages with images and line boxes."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    font = _student_font()
    width = PAGE_W - LEFT - RIGHT_MARGIN - TICK_GUTTER
    wrapped: list[tuple[str, OCRLine]] = []
    for page in pages:
        for line in page.lines:
            parts = _wrap_to_width(line.text, width) or [""]
            wrapped += [(t, line) for t in parts]
    rows_per_page = (PAGE_H - TOP - 80) // LINE_H
    out: list[OCRPage] = []
    for start in range(0, max(1, len(wrapped)), rows_per_page):
        idx = len(out)
        img = Image.new("RGB", (PAGE_W, PAGE_H), (253, 252, 247))
        d = ImageDraw.Draw(img)
        for r in range(rows_per_page + 1):
            y = TOP + r * LINE_H + LINE_H - 8
            d.line([(40, y), (PAGE_W - 40, y)], fill=(200, 214, 232), width=1)
        d.line([(LEFT - 20, 0), (LEFT - 20, PAGE_H)], fill=(232, 150, 150), width=2)
        d.line([(PAGE_W - RIGHT_MARGIN + 10, 0), (PAGE_W - RIGHT_MARGIN + 10, PAGE_H)], fill=(232, 150, 150), width=2)
        d.text((LEFT, 40), f"Answer sheet: {student_id}   page {idx + 1}", fill=(120, 120, 120), font=_student_font(22))
        lines = []
        for r, (text, src) in enumerate(wrapped[start : start + rows_per_page]):
            y = TOP + r * LINE_H
            if not text.strip():
                continue
            line_font = _student_font(script_text=text) if _script_font(text, ink=False) else font
            d.text((LEFT, y + 18), text, fill=STUDENT_INK, font=line_font)
            x1 = LEFT + d.textlength(text, font=line_font)
            lines.append(
                src.model_copy(update={"text": text, "bbox": BBox(x0=LEFT, y0=y + 12, x1=x1, y1=y + LINE_H - 6)})
            )
        path = out_dir / f"{student_id}_typeset_{idx + 1}.png"
        img.save(path)
        out.append(OCRPage(page_index=idx, image_path=str(path), lines=lines, provider="typeset"))
    return out


def needs_typesetting(pages: list[OCRPage]) -> bool:
    """Return whether pages need a rendered text layout before annotation."""
    return not pages or any(
        not p.image_path or not Path(p.image_path).exists() or not any(line.bbox for line in p.lines) for p in pages
    )


def resegment(spec: ExamSpec, pages: list[OCRPage]) -> dict[str, AnswerSegment]:
    """Rebuild question segments using the rendered pages and line boxes."""
    from autoassess.segment import segment_pages

    return segment_pages(spec, pages)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


@dataclass
class _Hit:
    page: int
    line: OCRLine
    start: float  # 0..1 of the line's width
    end: float


def _find(q: str, lines: list[tuple[int, OCRLine]]) -> _Hit | None:
    for page, line in lines:
        t = _norm(line.text)
        if t and line.bbox is not None and q in t:
            i = t.index(q)
            return _Hit(page, line, i / len(t), (i + len(q)) / len(t))
    return None


def locate(quote: str, lines: list[tuple[int, OCRLine]], tail: bool = True) -> _Hit | None:
    """Find the line that holds a quote and where in the line it sits.

    A quote often runs over several written lines. Then the hit is the line
    where it ends (tail=True, where an examiner puts the tick) or starts,
    found from the quote's last or first few words.
    """
    from difflib import SequenceMatcher

    q = _norm(quote)
    if not q:
        return None
    if hit := _find(q, lines):
        return hit
    words = q.split()
    for n in (6, 4, 3, 2):
        if len(words) > n:
            part = " ".join(words[-n:] if tail else words[:n])
            if hit := _find(part, lines):
                return hit
    best, best_score = None, 0.0
    for page, line in lines:
        t = _norm(line.text)
        if not t or line.bbox is None:
            continue
        m = SequenceMatcher(None, q, t, autojunk=False).find_longest_match(0, len(q), 0, len(t))
        score = m.size / min(len(q), len(t))
        if score > best_score:
            best, best_score = _Hit(page, line, m.b / len(t), (m.b + m.size) / len(t)), score
    return best if best_score >= 0.6 else None


def plan_annotations(
    spec: ExamSpec, grade: SheetGrade, segments: dict[str, AnswerSegment], pages: list[OCRPage]
) -> AnnotationPlan:
    """Locate evidence and plan red-ink awards, corrections and review symbols."""
    sizes = {p.page_index: _page_size(p) for p in pages}
    pos = {p.page_index: i for i, p in enumerate(pages)}
    marks: list[Mark] = []
    praise_left = 2
    margin_free: dict[int, float] = {}  # page -> first free y in the right margin
    starts: dict[int, list[float]] = defaultdict(list)  # page -> y where each answer starts
    for qg in grade.questions:
        seg = segments.get(qg.question_id)
        for pg in seg.pages[:1] if seg else []:
            if own := _page_lines(pages, pg, seg):
                starts[pos[pg]].append(own[0].bbox.y0)

    def sheet_order(qg: QuestionGrade) -> tuple[int, float]:
        # Students answer out of order; lay margin notes out in the order they appear on the sheet.
        """Sort question grades by their first location on the answer sheet."""
        seg = segments.get(qg.question_id)
        own = _page_lines(pages, seg.pages[0], seg) if seg and seg.pages else []
        return (pos[seg.pages[0]], own[0].bbox.y0) if own else (10**6, 0.0)

    for qg in sorted(grade.questions, key=sheet_order):
        seg = segments.get(qg.question_id)
        lines = [(pg, ln) for pg in (seg.pages if seg else []) for ln in _page_lines(pages, pg, seg)]
        if not lines:
            continue
        crit = {c.id: c for c in spec.question(qg.question_id).criteria}
        first_page, first = lines[0]
        last_page, last = lines[-1]
        W, H = sizes[first_page]
        scale = max(0.6, min(1.6, W / PAGE_W))
        sz = 34 * scale
        p0 = pos[first_page]
        # Left margin: the question total, circled.
        total = f"{fmt_marks(qg.marks_awarded)}/{fmt_marks(qg.max_marks)}"
        marks.append(
            Mark(
                kind="circle",
                page=p0,
                x=max(8, first.bbox.x0 - 130 * scale),
                y=first.bbox.y0 - 6 * scale,
                text=total,
                size=sz,
            )
        )
        # Right margin: sub-part marks in brackets, and "?" when sent for review.
        rx = min(W - 120 * scale, max(first.bbox.x1 + 40 * scale, W - (RIGHT_MARGIN - 30) * scale))
        marks.append(
            Mark(
                kind="text",
                page=p0,
                x=rx,
                y=first.bbox.y0 - 4 * scale,
                text=f"({fmt_marks(qg.marks_awarded)})",
                size=sz,
            )
        )
        if qg.needs_review:
            marks.append(
                Mark(kind="question", page=p0, x=rx + 90 * scale, y=first.bbox.y0 - 10 * scale, text="?", size=sz * 1.4)
            )
        # Ticks at the evidence, one per mark, kept out of the margin column. When the
        # evidence line has no room left, the marks go on the next line of the answer.
        tick_slots: dict[int, float] = {}
        limit = rx - 30 * scale
        praise_at: tuple[int, OCRLine, float] | None = None  # after the last fully met criterion's ticks
        tick_w = 26 * scale

        for r in qg.criteria:
            if r.marks_awarded <= 0:
                continue
            hit = locate(r.evidence or "", lines) if r.evidence else None
            at = next((i for i, (_, ln) in enumerate(lines) if hit and ln is hit.line), len(lines) - 1)
            n = int(r.marks_awarded)
            frac = r.marks_awarded - n
            tags = [label for tag, label in (("ecf", "ECF"), ("bod", "BOD")) if tag in r.tags]
            need = n * tick_w + (24 * scale if frac > 0 else 0) + 56 * scale * len(tags)
            # The evidence line, then the lines after it, then the ones before.
            order = list(range(at, len(lines))) + list(range(at - 1, -1, -1))
            # A line's first free x is just after its text, or after marks already on it.
            free = [tick_slots.get(id(ln), ln.bbox.x1 + 14 * scale) for _, ln in lines]
            pick = next((i for i in order if free[i] + need <= limit), at)
            page, line = lines[pick]
            x = min(free[pick], limit - need)
            for _ in range(max(n, 0)):
                marks.append(
                    Mark(
                        kind="tick",
                        page=pos[page],
                        x=x,
                        y=line.bbox.y0,
                        w=tick_w,
                        h=line.bbox.y1 - line.bbox.y0,
                        size=sz,
                    )
                )
                x += tick_w
            if frac > 0:
                marks.append(
                    Mark(
                        kind="text",
                        page=pos[page],
                        x=x,
                        y=line.bbox.y0 - 4 * scale,
                        text=fmt_marks(frac),
                        size=sz * 0.7,
                    )
                )
                x += 24 * scale
            for label in tags:
                marks.append(
                    Mark(
                        kind="text",
                        page=pos[page],
                        x=x + 4 * scale,
                        y=line.bbox.y0 - 2 * scale,
                        text=label,
                        size=sz * 0.65,
                    )
                )
                x += 56 * scale
            if r.marks_awarded >= crit[r.criterion_id].marks and n >= 1 and hit is not None:
                praise_at = (page, line, x)
            tick_slots[id(line)] = x + 6 * scale
        # "Good!" at most once per answer, after its ticks, for a strong answer, and only where it fits.
        if praise_at and praise_left and qg.marks_awarded >= 0.8 * qg.max_marks:
            page, line, _ = praise_at
            x = tick_slots[id(line)]
            if x + 90 * scale <= limit:
                marks.append(
                    Mark(kind="text", page=pos[page], x=x, y=line.bbox.y0 - 6 * scale, text="Good!", size=sz * 0.9)
                )
                tick_slots[id(line)] = x + 96 * scale
                praise_left -= 1
        # Wavy underline under wrong statements, correction above the line.
        for e in qg.errors:
            hit = locate(e.quote, lines, tail=False)
            if not hit:
                continue
            b = hit.line.bbox
            x0, x1 = b.x0 + hit.start * (b.x1 - b.x0), b.x0 + hit.end * (b.x1 - b.x0)
            marks.append(
                Mark(kind="wavy", page=pos[hit.page], x=x0, y=b.y1 + 2 * scale, w=max(30 * scale, x1 - x0), size=sz)
            )
            if e.correction:
                marks.append(
                    Mark(kind="text", page=pos[hit.page], x=x0, y=b.y0 - 34 * scale, text=e.correction, size=sz * 0.62)
                )
        # Caret at the end of an answer that lost marks, with the fix.
        if qg.marks_awarded < qg.max_marks and qg.remark and qg.remark.fix:
            lb = last.bbox
            # Under the last word, so it never sits on top of the ticks that follow the text.
            marks.append(Mark(kind="caret", page=pos[last_page], x=lb.x1 - 22 * scale, y=lb.y1 - 4 * scale, size=sz))
        # Margin remark under the bracketed marks.
        if qg.remark:
            y = max(first.bbox.y0 + 44 * scale, margin_free.get(p0, 0.0))
            stop = min([v - 12 * scale for v in starts[p0] if v > first.bbox.y0 + 1], default=H - 60 * scale)
            width_chars = max(14, int((W - rx - 10) / (12 * scale)))
            for part in qg.remark.lines():
                for chunk in textwrap.wrap(part, width=width_chars, max_lines=3, placeholder="…"):
                    if y + 26 * scale > stop:
                        break  # no room before the next answer; the notes page has the full remark
                    marks.append(Mark(kind="text", page=p0, x=rx - 10 * scale, y=y, text=chunk, size=sz * 0.62))
                    y += 26 * scale
            margin_free[p0] = y + 14 * scale
    conf = min((q.confidence for q in grade.questions), default=1.0)
    return AnnotationPlan(
        student_id=grade.student_id,
        pages=[p.image_path or "" for p in pages],
        marks=marks,
        cover=[
            (q.question_id, f"{fmt_marks(q.marks_awarded)}" + (" ?" if q.needs_review else "")) for q in grade.questions
        ],
        total=f"{fmt_marks(grade.total)} / {fmt_marks(spec.total_marks)}",
        confidence=round(sum(q.confidence for q in grade.questions) / max(1, len(grade.questions)), 2)
        if grade.questions
        else conf,
        review=[q.question_id for q in grade.questions if q.needs_review],
        notes=_notes(spec, grade),
    )


def _page_lines(pages: list[OCRPage], page_index: int, seg: AnswerSegment | None) -> list[OCRLine]:
    page = next((p for p in pages if p.page_index == page_index), None)
    if page is None or seg is None:
        return []
    wanted = {id(line) for line in seg.lines}
    own = [line for line in page.lines if id(line) in wanted and line.bbox and line.text.strip()]
    if own:
        return own
    # Lines were copied (e.g. after anonymising): match by text instead.
    texts = {_norm(line.text) for line in seg.lines}
    return [line for line in page.lines if line.bbox and line.text.strip() and _norm(line.text) in texts]


def _page_size(page: OCRPage) -> tuple[int, int]:
    from PIL import Image

    with Image.open(page.image_path) as im:
        return im.size


def _notes(spec: ExamSpec, grade: SheetGrade) -> list[str]:
    out = []
    for q in grade.questions:
        out.append(f"{q.question_id}")
        if q.remark:
            out += [f"  {line}" for line in q.remark.lines()]
        for e in q.errors:
            out.append(f'  Check: "{e.quote}" -> {e.correction}')
        out.append(
            f"  Marks: {fmt_marks(q.marks_awarded)} of {fmt_marks(q.max_marks)}"
            + ("   ? to be checked by a teacher" if q.needs_review else "")
        )
    if grade.summary_feedback:
        out += ["", grade.summary_feedback]
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _ink_text(img, xy, text: str, size: float, bold: bool = False, fill=INK):
    from PIL import Image, ImageDraw

    font = _font(int(size), bold, text)
    w = int(ImageDraw.Draw(img).textlength(text, font=font)) + 20
    h = int(size * 1.6) + 10
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((8, 2), text, font=font, fill=(*fill, 235))
    img.alpha_composite(layer, (int(xy[0]), int(xy[1])))
    return w


def _tick(d, m: Mark):
    s = m.w
    base_y = m.y + m.h * 0.75
    pts = [
        (m.x, base_y - s * 0.35),
        (m.x + s * 0.35, base_y),
        (m.x + s * 1.05, base_y - s * 1.1),
    ]
    d.line(pts, fill=(*INK, 240), width=max(3, int(m.size / 9)), joint="curve")


def _wavy(d, m: Mark):
    amp, period = m.size * 0.12, m.size * 0.45
    pts = [(m.x + t, m.y + amp * math.sin(2 * math.pi * t / period)) for t in range(0, int(m.w) + 1, 3)]
    if len(pts) > 1:
        d.line(pts, fill=(*INK, 230), width=max(2, int(m.size / 12)))


def _caret(d, m: Mark):
    s = m.size * 0.5
    d.line([(m.x, m.y + s), (m.x + s * 0.5, m.y), (m.x + s, m.y + s)], fill=(*INK, 240), width=max(3, int(m.size / 10)))


def _stamp(img, xy, lines: list[str], size: float):
    from PIL import Image, ImageDraw

    font = _font(int(size), True, " ".join(lines))
    d0 = ImageDraw.Draw(img)
    w = int(max(d0.textlength(t, font=font) for t in lines)) + 40
    h = int(len(lines) * size * 1.35) + 30
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([3, 3, w - 4, h - 4], radius=12, outline=(*INK, 210), width=4)
    for i, t in enumerate(lines):
        d.text((20, 14 + i * size * 1.35), t, font=font, fill=(*INK, 210))
    img.alpha_composite(layer, (int(xy[0]), int(xy[1])))


def render_cover(plan: AnnotationPlan, title: str):
    """Draw the booklet cover with the question grid and total."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (PAGE_W, PAGE_H), (250, 248, 240, 255))
    d = ImageDraw.Draw(img)
    pf = _student_font(40)
    d.rectangle([60, 60, PAGE_W - 60, PAGE_H - 60], outline=(60, 60, 60), width=3)
    d.text((110, 110), "ANSWER BOOKLET", fill=(40, 40, 40), font=pf)
    d.text((110, 170), title[:60], fill=(70, 70, 70), font=_student_font(28, title[:60]))
    d.text((110, 230), f"Candidate: {plan.student_id}", fill=(70, 70, 70), font=_student_font(28))
    d.text((110, 330), "FOR EXAMINER'S USE ONLY", fill=(40, 40, 40), font=_student_font(30))
    # The marks grid, printed; the examiner's entries are in red.
    x0, y0, cw, rh = 110, 390, 300, 64
    rows = plan.cover + [("Total", plan.total)]
    d.rectangle([x0, y0, x0 + 2 * cw, y0 + rh], outline=(60, 60, 60), width=2)
    d.text((x0 + 20, y0 + 16), "Question", fill=(40, 40, 40), font=_student_font(28))
    d.text((x0 + cw + 20, y0 + 16), "Marks", fill=(40, 40, 40), font=_student_font(28))
    for i, (q, mk) in enumerate(rows, 1):
        y = y0 + i * rh
        d.rectangle([x0, y, x0 + cw, y + rh], outline=(60, 60, 60), width=2)
        d.rectangle([x0 + cw, y, x0 + 2 * cw, y + rh], outline=(60, 60, 60), width=2)
        d.text((x0 + 20, y + 16), q, fill=(40, 40, 40), font=_student_font(28, q))
        _ink_text(img, (x0 + cw + 24, y + 2), mk, 40 if q == "Total" else 36, bold=q == "Total")
    yb = y0 + (len(rows) + 1) * rh + 20
    _stamp(
        img,
        (x0 + 2 * cw + 60, y0 + 40),
        ["AI-marked", VERSION, f"confidence {plan.confidence:.0%}"],
        34,
    )
    if plan.review:
        _ink_text(img, (x0, yb), f"? to be checked by a teacher: {', '.join(plan.review)}", 32)
        yb += 60
    _ink_text(img, (x0, yb), "Feedback for each answer is on the last page.", 30)
    return img


def render_notes(plan: AnnotationPlan):
    """Draw feedback pages for the annotation plan."""
    from PIL import Image

    pages = []
    img, y = None, 0
    for line in plan.notes:
        width = 46 if _script_font(line, ink=True) not in (None, "Kalam") else 62  # Kannada/Tamil/Telugu run wider
        for chunk in textwrap.wrap(line, width=width, subsequent_indent="    ") or [""]:
            if img is None or y > PAGE_H - 120:
                img = Image.new("RGBA", (PAGE_W, PAGE_H), (253, 252, 247, 255))
                pages.append(img)
                _ink_text(img, (110, 70), "Examiner's notes", 46, bold=True)
                y = 160
            if chunk:
                header = not chunk.startswith(" ") and len(chunk) <= 6
                _ink_text(img, (110, y), chunk, 36 if header else 30, bold=header)
            y += 46
    if pages:
        if y > PAGE_H - 320:
            img = Image.new("RGBA", (PAGE_W, PAGE_H), (253, 252, 247, 255))
            pages.append(img)
            y = 160
        _stamp(pages[-1], (PAGE_W - 470, y + 40), ["AI-marked", VERSION], 30)
    return pages


def render_plan(plan: AnnotationPlan, title: str = "", cover: bool = True, notes: bool = True):
    """Draw the plan. Returns a list of RGB PIL images: cover, annotated pages, notes."""
    from PIL import Image, ImageDraw

    out = []
    if cover:
        out.append(render_cover(plan, title))
    for i, path in enumerate(plan.pages):
        img = Image.open(path).convert("RGBA")
        d = ImageDraw.Draw(img, "RGBA")
        for m in (m for m in plan.marks if m.page == i):
            if m.kind == "tick":
                _tick(d, m)
            elif m.kind == "wavy":
                _wavy(d, m)
            elif m.kind == "caret":
                _caret(d, m)
            elif m.kind in ("text", "question"):
                _ink_text(img, (m.x, m.y), m.text, m.size, bold=m.kind == "question")
            elif m.kind == "circle":
                w = _ink_text(img, (m.x, m.y), m.text, m.size, bold=True)
                d.ellipse(
                    [m.x - 6, m.y - 4, m.x + w + 2, m.y + m.size * 1.5],
                    outline=(*INK, 220),
                    width=max(3, int(m.size / 11)),
                )
        if i == 0:
            _stamp(img, (img.width - 330, img.height - 150), ["AI-marked"], 28)
        out.append(img)
    if notes:
        out += render_notes(plan)
    return [im.convert("RGB") for im in out]


@dataclass
class AnnotatedSheet:
    """Paths to the completed marked PDF and page images."""

    plan: AnnotationPlan
    pdf: Path
    pngs: list[Path]


def annotate_sheet(
    spec: ExamSpec,
    grade: SheetGrade,
    segments: dict[str, AnswerSegment],
    pages: list[OCRPage],
    out_dir: str | Path,
    *,
    cover: bool = True,
    notes: bool = True,
) -> AnnotatedSheet:
    """Plan, render and save: <out>/<student>_marked.pdf plus one PNG per page."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if needs_typesetting(pages):
        pages = typeset(pages, out / "typeset", grade.student_id)
        segments = resegment(spec, pages)
    plan = plan_annotations(spec, grade, segments, pages)
    images = render_plan(plan, spec.title, cover=cover, notes=notes)
    pngs = []
    for i, im in enumerate(images, 1):
        p = out / f"{grade.student_id}_marked_{i:02d}.png"
        im.save(p)
        pngs.append(p)
    pdf = out / f"{grade.student_id}_marked.pdf"
    images[0].save(pdf, save_all=True, append_images=images[1:], resolution=150)
    (out / f"{grade.student_id}_annotations.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return AnnotatedSheet(plan, pdf, pngs)


def question_grade_for(grade: SheetGrade, qid: str) -> QuestionGrade | None:
    """Find a question's grade, returning None when it is absent."""
    return next((q for q in grade.questions if q.question_id == qid), None)
