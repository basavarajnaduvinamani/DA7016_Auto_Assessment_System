"""Self-contained HTML report for one graded sheet.

Shows the mark sheet, then per question: the student's answer with the
evidence quotes highlighted, the criterion-by-criterion verdicts, the
feedback, any flags, and (when OCR gave boxes) the scanned page with the
evidence lines outlined.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from pathlib import Path

from autoassess.schemas import AnswerSegment, ExamSpec, OCRPage, SheetGrade

_WORD = re.compile(r"[\w']+")


def _norm_with_index(text: str) -> tuple[str, list[int]]:
    """Lowercased words joined by single spaces, and each char's index in `text`."""
    out, idx = [], []
    for m in _WORD.finditer(text):
        if out:
            out.append(" ")
            idx.append(m.start())
        for k, ch in enumerate(m.group(0)):
            out.append(ch.lower())
            idx.append(m.start() + k)
    return "".join(out), idx


def find_span(evidence: str, answer: str) -> tuple[int, int] | None:
    """Character span of `evidence` inside `answer`, ignoring case and punctuation."""
    q, _ = _norm_with_index(evidence)
    hay, idx = _norm_with_index(answer)
    if not q:
        return None
    pos = hay.find(q)
    if pos == -1:
        return None
    end = pos + len(q) - 1
    return idx[pos], idx[end] + 1


def _highlight(answer: str, quotes: list[tuple[str, str]]) -> str:
    """HTML of the answer with each (quote, label) marked."""
    spans = []
    for quote, label in quotes:
        span = find_span(quote, answer) if quote else None
        if span:
            spans.append((*span, label))
    spans.sort()
    out, pos = [], 0
    for start, end, label in spans:
        if start < pos:
            continue  # overlapping quote: keep the first
        out.append(html.escape(answer[pos:start]))
        out.append(f'<mark title="{html.escape(label)}">{html.escape(answer[start:end])}</mark>')
        pos = end
    out.append(html.escape(answer[pos:]))
    return "".join(out).replace("\n", "<br>")


def _page_figure(page: OCRPage, segment: AnswerSegment, quotes: list[str]) -> str:
    if not page.image_path or not Path(page.image_path).exists():
        return ""
    page_lines = {id(line) for line in page.lines}
    norm_quotes = [_norm_with_index(q)[0] for q in quotes if q]
    rects = []
    for line in segment.lines:
        if line.bbox is None or id(line) not in page_lines:
            continue
        lt = _norm_with_index(line.text)[0]
        if len(lt) >= 4 and any(lt in q or q in lt for q in norm_quotes):
            b = line.bbox
            rects.append(f'<rect x="{b.x0}" y="{b.y0}" width="{b.x1 - b.x0}" height="{b.y1 - b.y0}"/>')
    if not rects:
        return ""
    data = Path(page.image_path).read_bytes()
    mime = mimetypes.guess_type(page.image_path)[0] or "image/png"
    try:
        from PIL import Image

        with Image.open(page.image_path) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001 - size is only needed for the overlay
        w, h = 1000, 1400
    src = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return (
        f'<figure><svg viewBox="0 0 {w} {h}" class="page"><image href="{src}" width="{w}" height="{h}"/>'
        f'<g class="ev">{"".join(rects)}</g></svg><figcaption>Page {page.page_index + 1}: evidence lines outlined</figcaption></figure>'
    )


def _tags(tags: list[str]) -> str:
    return "".join(f"<span class=tag>{html.escape(t)}</span>" for t in tags)


CSS = """
:root{--ink:#1d1d1f;--quiet:#5f6368;--line:#dadce0;--bg:#fff;--card:#f8f9fa;--good:#1e8e3e;--part:#b06000;--bad:#c5221f;--mark:#fff3b0}
@media (prefers-color-scheme:dark){:root{--ink:#e8eaed;--quiet:#9aa0a6;--line:#3c4043;--bg:#121212;--card:#1e1f21;--good:#81c995;--part:#fdd663;--bad:#f28b82;--mark:#5c4a00}}
body{font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg);max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}.quiet{color:var(--quiet)}
table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600}.num{text-align:right;white-space:nowrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:8px 0}
.met,.partial,.not_met{white-space:nowrap}.met{color:var(--good)}.partial{color:var(--part)}.not_met{color:var(--bad)}
mark{background:var(--mark);color:inherit;padding:0 2px;border-radius:2px}
.review{color:var(--bad);font-size:18px}.tag{font-size:11px;color:var(--quiet);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:4px}
.flag{display:inline-block;border:1px solid var(--part);color:var(--part);border-radius:12px;padding:0 8px;margin:2px 4px 2px 0;font-size:12px}
svg.page{width:100%;height:auto;border:1px solid var(--line)}.ev rect{fill:none;stroke:#f9ab00;stroke-width:4}
ul{margin:4px 0 4px 20px;padding:0}
"""


def render_html(spec: ExamSpec, grade: SheetGrade, segments: dict[str, AnswerSegment], pages: list[OCRPage] | None = None) -> str:
    pages = pages or []
    esc = html.escape
    rows = "".join(
        f'<tr><td><a href="#{esc(q.question_id)}">{esc(q.question_id)}</a></td><td class="num">{q.marks_awarded:g} / {q.max_marks:g}</td>'
        f'<td class="num">{q.confidence:.0%}{" <strong class=review title=\'sent for human review\'>?</strong>" if q.needs_review else ""}</td><td>{"".join(f"<span class=flag>{esc(f)}</span>" for f in q.flags)}</td></tr>'
        for q in grade.questions
    )
    parts = [
        f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{esc(grade.student_id)}: {esc(spec.title)}</title><style>{CSS}</style></head><body>",
        f"<h1>{esc(spec.title)}</h1><p class=quiet>Student {esc(grade.student_id)} &middot; {grade.total:g} of {spec.total_marks:g} marks</p>",
        f"<div class=card>{esc(grade.summary_feedback)}</div>" if grade.summary_feedback else "",
        f"<table><tr><th>Question</th><th class=num>Marks</th><th class=num>Confidence</th><th>Flags</th></tr>{rows}</table>",
    ]
    for q in grade.questions:
        question = spec.question(q.question_id)
        seg = segments.get(q.question_id) or AnswerSegment(question_id=q.question_id, text="")
        crit = {c.id: c for c in question.criteria}
        quotes = [(r.evidence or "", r.criterion_id) for r in q.criteria if r.marks_awarded > 0]
        parts.append(f'<h2 id="{esc(q.question_id)}">{esc(q.question_id)} &middot; {q.marks_awarded:g} / {q.max_marks:g}</h2>')
        parts.append(f"<p class=quiet>{esc(question.text)}</p>")
        if q.remark and q.remark.lines():
            # The remark comes before the marks table: comments first, numbers second.
            parts.append("<div class=card>" + "<br>".join(esc(line) for line in q.remark.lines()) + "</div>")
        answer_html = _highlight(seg.text, quotes) if seg.text else "<em>No answer found.</em>"
        parts.append(f"<div class=card>{answer_html}</div>")
        crit_rows = "".join(
            f'<tr><td>{esc(r.criterion_id)}</td><td>{esc(crit[r.criterion_id].description)}</td>'
            f'<td class="{r.verdict.value}">{r.verdict.value.replace("_", " ")}</td><td class=num>{r.marks_awarded:g} / {crit[r.criterion_id].marks:g}{_tags(r.tags)}</td>'
            f'<td>{("&ldquo;" + esc(r.evidence) + "&rdquo; ") if r.evidence else ""}<span class=quiet>{esc(r.reason)}</span></td></tr>'
            for r in q.criteria
        )
        parts.append(
            f"<table><tr><th>Criterion</th><th>Rubric</th><th>Verdict</th><th class=num>Marks</th><th>Evidence and reason</th></tr>{crit_rows}</table>"
        )
        earned = [i for i in q.feedback_items if i.kind == "earned"]
        lost = [i for i in q.feedback_items if i.kind == "lost"]
        if earned or lost:
            fb = ""
            if earned:
                fb += "<p><strong>What earned marks</strong></p><ul>" + "".join(f"<li>{esc(i.text)}</li>" for i in earned) + "</ul>"
            if lost:
                fb += "<p><strong>Where marks were lost</strong></p><ul>" + "".join(
                    f"<li>{esc(i.text)}" + (f"<br><strong>Next time:</strong> {esc(i.next_step)}" if i.next_step else "") + "</li>" for i in lost
                ) + "</ul>"
            parts.append(f"<div class=card>{fb}</div>")
        elif q.feedback:
            parts.append(f"<div class=card>{esc(q.feedback).replace(chr(10), '<br>')}</div>")
        for page in pages:
            if page.page_index in seg.pages:
                parts.append(_page_figure(page, seg, [qt for qt, _ in quotes]))
    parts.append("</body></html>")
    return "".join(parts)
