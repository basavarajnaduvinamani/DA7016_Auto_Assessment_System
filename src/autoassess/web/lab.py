"""Web demo: upload an answer sheet, get it back marked in red ink.

Imported lazily by the teacher app at /lab; python app.py still runs the lab.
On Render:    render.yaml deploys this as a free web service; set the keys as
              environment variables in the Render dashboard (see docs/deploy.md).
"""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr
from fastapi import FastAPI

from autoassess.demo import (
    LANGUAGES, SAMPLE, UPLOAD_EXTENSIONS, Options, demo_settings, health_payload,
    llm_available, mark_class, mark_sheet, status_markdown,
)
from autoassess.spec_builder import lint_spec, load_spec
from autoassess.web.brand import CSS, HEADER, THEME

INPUTS = {"OCR text": "text", "Page image": "image", "Both (hybrid)": "hybrid"}


def _spec(spec_file):
    return load_spec(spec_file or SAMPLE / "exam_spec.yaml")


def do_mark(spec_file, sheet_file, grader, input_mode, advocate_review, language, strict_critic=False):
    if sheet_file is None:
        raise gr.Error("Upload an answer sheet: a PDF, a photo, or a .txt file.")
    try:
        spec = _spec(spec_file)
    except Exception:
        raise gr.Error("The exam spec could not be read. Check the YAML/JSON or use the sample quiz.") from None
    opts = Options(use_llm=grader == "LLM grader", input_mode=INPUTS[input_mode], advocate_review=advocate_review, strict_critic=strict_critic, language=language)
    try:
        r = mark_sheet(spec, sheet_file, opts)
    except ValueError as err:
        raise gr.Error(str(err)) from None
    except Exception:
        raise gr.Error("The sheet could not be marked. Try the sample sheet or a valid typed .txt file.") from None
    notes = "\n".join(f"> {n}" for n in r.notes + [f"Rubric check: {w}" for w in lint_spec(spec)])
    choices = [f"{q.question_id} / {c.criterion_id} ({c.marks_awarded:g})" for q in r.grade.questions for c in q.criteria]
    return (
        [str(p) for p in r.pages],
        (notes + "\n\n" if notes else "") + r.summary_md,
        str(r.pdf_path) if r.pdf_path else None,
        r.html_path.read_text(encoding="utf-8"),
        gr.update(choices=choices, value=choices[0] if choices else None),
        status_markdown(),
        (spec, r, sheet_file),
    )


def do_regrade(choice, reason, last):
    from autoassess.providers import make_llm
    from autoassess.regrade import regrade

    if last is None:
        raise gr.Error("Mark a sheet first.")
    if not reason or not reason.strip():
        raise gr.Error("Say why the mark should change.")
    if not choice:
        raise gr.Error("Choose a mark to review.")
    spec, r, _ = last
    try:
        qid, criterion = choice.split(" / ", 1)
        cid = criterion.split(" ")[0]
        answer = r.run.segments[qid].text
        if not any(q.question_id == qid and any(c.criterion_id == cid for c in q.criteria) for q in r.grade.questions):
            raise ValueError("Unknown criterion")
    except (AttributeError, KeyError, TypeError, ValueError):
        raise gr.Error("That answer or mark is unavailable. Mark the sheet again and choose a mark to review.") from None
    settings = demo_settings()
    if not llm_available(settings):
        raise gr.Error("Regrade requests need the LLM grader (no key is set).")
    try:
        new, rec = regrade(spec, r.grade, answer, qid, cid, reason, make_llm(settings), log=Path(settings.cache_dir) / "regrades.jsonl")
    except Exception:
        return "Regrade service unavailable. The original mark is unchanged; ask a teacher to review it."
    r.grade = new
    return f"**{cid}: {rec.old_marks:g} → {rec.new_marks:g}** ({rec.decision})\n\n{rec.response or rec.reason}"


def do_class(spec_file, files, grader, advocate_review, strict_critic=False):
    if not files:
        raise gr.Error("Upload two or more answer sheets.")
    try:
        spec = _spec(spec_file)
    except Exception:
        raise gr.Error("The exam spec could not be read. Check the YAML/JSON or use the sample quiz.") from None
    try:
        rpath, zpath, notes = mark_class(spec, files, Options(use_llm=grader == "LLM grader", advocate_review=advocate_review, strict_critic=strict_critic))
    except ValueError as err:
        raise gr.Error(str(err)) from None
    except Exception:
        raise gr.Error("The class could not be marked. Check the uploads or try the sample sheet.") from None
    return rpath.read_text(encoding="utf-8"), str(zpath), "\n".join(f"> {n}" for n in notes), status_markdown()


def do_sample():
    grader = "LLM grader" if llm_available(demo_settings()) else "Lexical baseline"
    return do_mark(None, str(SAMPLE / "answer_sheets" / "S002.txt"), grader, "OCR text", True, "English")


ABOUT = """
### How it marks
1. **Reads the sheet.** Typed text as is; scans with Bodhan IndicOCR (Indian languages), or a vision model.
2. **Grades each rubric point** with an LLM, three times, keeping the median. Every mark must quote the student's own words, checked in code.
3. **Advocate review by default.** An advocate can raise a missed mark only with a verified quote; the strict critic is optional and can only lower marks. The SPRAG dev ablation selected advocate-only review for its lowest MAE and near-zero bias, while the critic increased under-marking.
4. **Knows when to defer.** Run spread, a second examiner, OCR confidence and the reviewers' changes give a confidence. Low confidence is marked **?** for a teacher.
5. **Writes on the sheet** like an Indian examiner: a tick per mark, bracketed marks, a circled total, the marks grid on the cover, and a short remark: one strength, one fix, one thing for next time.

Every sheet carries an **AI-marked** stamp. The handwriting is so students read it like teacher feedback, not to hide where it came from.
"""

settings = demo_settings()
llm_enabled = llm_available(settings)
grader_choices = ["LLM grader", "Lexical baseline"] if llm_enabled else ["Lexical baseline"]

with gr.Blocks(title="Red-Ink Grader", analytics_enabled=False) as demo:
    gr.HTML(HEADER)
    last_result = gr.State(value=None)
    status = gr.Markdown(status_markdown())
    with gr.Tab("Mark a sheet"):
        with gr.Row():
            sheet_in = gr.File(label="Answer sheet (PDF, photo or .txt)", type="filepath", file_types=list(UPLOAD_EXTENSIONS))
            spec_in = gr.File(label="Exam spec (YAML/JSON). Empty = sample quiz", file_types=[".yaml", ".yml", ".json"], type="filepath")
        with gr.Row():
            grader_in = gr.Radio(grader_choices, value=grader_choices[0], label="Grader", interactive=llm_enabled)
            input_in = gr.Radio(list(INPUTS), value="OCR text", label="What the grader reads")
            advocate_in = gr.Checkbox(value=True, label="Advocate review")
            critic_in = gr.Checkbox(value=False, label="Strict critic (lowers marks; off by default)")
            lang_in = gr.Dropdown(LANGUAGES, value="English", label="Feedback language")
        go = gr.Button("Mark it", variant="primary")
        sample = gr.Button("Try the sample sheet")
        gallery = gr.Gallery(label="Marked sheet", columns=2, height=720, object_fit="contain")
        with gr.Row():
            summary = gr.Markdown()
            pdf = gr.File(label="Download marked PDF")
        with gr.Accordion("Full report: every criterion, quote and reason", open=False):
            report = gr.HTML()
        with gr.Accordion("Ask for a regrade", open=False):
            crit_in = gr.Dropdown(label="Which mark", choices=[])
            reason_in = gr.Textbox(label="Why should it change?", lines=2)
            rg = gr.Button("Request regrade")
            rg_out = gr.Markdown()
        gr.Examples([[str(SAMPLE / "answer_sheets" / name)] for name in ("S001.txt", "S002.txt", "S003.txt", "S002_scan.pdf")], inputs=[sheet_in], label="Sample sheets")
        go.click(do_mark, [spec_in, sheet_in, grader_in, input_in, advocate_in, lang_in, critic_in], [gallery, summary, pdf, report, crit_in, status, last_result])
        sample.click(do_sample, outputs=[gallery, summary, pdf, report, crit_in, status, last_result])
        rg.click(do_regrade, [crit_in, reason_in, last_result], [rg_out])
    with gr.Tab("Mark a class"):
        with gr.Row():
            files_in = gr.File(label="Answer sheets", file_count="multiple", type="filepath", file_types=list(UPLOAD_EXTENSIONS))
            cspec_in = gr.File(label="Exam spec. Empty = sample quiz", file_types=[".yaml", ".yml", ".json"], type="filepath")
        with gr.Row():
            cgrader_in = gr.Radio(grader_choices, value=grader_choices[0], label="Grader", interactive=llm_enabled)
            cadvocate_in = gr.Checkbox(value=True, label="Advocate review")
            ccritic_in = gr.Checkbox(value=False, label="Strict critic (lowers marks; off by default)")
        cgo = gr.Button("Mark the class", variant="primary")
        cnotes = gr.Markdown()
        czip = gr.File(label="Marked sheets, grades and report (zip)")
        creport = gr.HTML()
        cgo.click(do_class, [cspec_in, files_in, cgrader_in, cadvocate_in, ccritic_in], [creport, czip, cnotes, status])
    with gr.Tab("How it works"):
        gr.Markdown(ABOUT)

    demo.load(status_markdown, outputs=status)

app = FastAPI()


@app.get("/healthz")
def healthz():
    return health_payload()


app = gr.mount_gradio_app(
    app, demo.queue(default_concurrency_limit=2), path="/", show_error=False, theme=THEME, css=CSS,
    max_file_size=int(float(os.getenv("AUTOASSESS_MAX_UPLOAD_MB", "10")) * 1024 * 1024),
)
