"""Web demo: upload an answer sheet, get it back marked in red ink.

Run locally:  pip install -e ".[demo,ingest]" && python app.py
On Render:    render.yaml deploys this as a free web service; set the keys as
              environment variables in the Render dashboard (see docs/deploy.md).
"""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr

from autoassess.config import Settings
from autoassess.demo import LANGUAGES, SAMPLE, Options, mark_class, mark_sheet
from autoassess.spec_builder import lint_spec, load_spec

INPUTS = {"OCR text": "text", "Page image": "image", "Both (hybrid)": "hybrid"}
STATE: dict = {}


def _spec(spec_file):
    return load_spec(spec_file or SAMPLE / "exam_spec.yaml")


def do_mark(spec_file, sheet_file, grader, input_mode, two_sided, language):
    if sheet_file is None:
        raise gr.Error("Upload an answer sheet: a PDF, a photo, or a .txt file.")
    spec = _spec(spec_file)
    opts = Options(use_llm=grader == "LLM grader", input_mode=INPUTS[input_mode], two_sided=two_sided, language=language)
    try:
        r = mark_sheet(spec, sheet_file, opts)
    except ValueError as err:
        raise gr.Error(str(err)) from err
    STATE["last"] = (spec, r, sheet_file)
    notes = "\n".join(f"> {n}" for n in r.notes + [f"Rubric check: {w}" for w in lint_spec(spec)])
    choices = [f"{q.question_id} / {c.criterion_id} ({c.marks_awarded:g})" for q in r.grade.questions for c in q.criteria]
    return (
        [str(p) for p in r.pages],
        (notes + "\n\n" if notes else "") + r.summary_md,
        str(r.pdf_path) if r.pdf_path else None,
        r.html_path.read_text(encoding="utf-8"),
        gr.update(choices=choices, value=choices[0] if choices else None),
    )


def do_regrade(choice, reason):
    from autoassess.providers import make_llm
    from autoassess.regrade import regrade

    if "last" not in STATE:
        raise gr.Error("Mark a sheet first.")
    if not reason or not reason.strip():
        raise gr.Error("Say why the mark should change.")
    spec, r, _ = STATE["last"]
    settings = Settings.load()
    if not settings.llm_api_key:
        raise gr.Error("Regrade requests need the LLM grader (no key is set).")
    qid, cid = choice.split(" / ")[0], choice.split(" / ")[1].split(" ")[0]
    answer = r.run.segments[qid].text
    new, rec = regrade(spec, r.grade, answer, qid, cid, reason, make_llm(settings), log=Path(settings.cache_dir) / "regrades.jsonl")
    r.grade = new
    return f"**{cid}: {rec.old_marks:g} → {rec.new_marks:g}** ({rec.decision})\n\n{rec.response or rec.reason}"


def do_class(spec_file, files, grader, two_sided):
    if not files:
        raise gr.Error("Upload two or more answer sheets.")
    rpath, zpath, notes = mark_class(_spec(spec_file), files, Options(use_llm=grader == "LLM grader", two_sided=two_sided))
    return rpath.read_text(encoding="utf-8"), str(zpath), "\n".join(f"> {n}" for n in notes)


ABOUT = """
### How it marks
1. **Reads the sheet.** Typed text as is; scans with Bodhan IndicOCR (Indian languages), or a vision model.
2. **Grades each rubric point** with an LLM, three times, keeping the median. Every mark must quote the student's own words, checked in code.
3. **Two-sided review.** A critic can lower a generous mark; an advocate can raise a missed one, but only with a quote.
4. **Knows when to defer.** Run spread, a second examiner, OCR confidence and the reviewers' changes give a confidence. Low confidence is marked **?** for a teacher.
5. **Writes on the sheet** like an Indian examiner: a tick per mark, bracketed marks, a circled total, the marks grid on the cover, and a short remark: one strength, one fix, one thing for next time.

Every sheet carries an **AI-marked** stamp. The handwriting is so students read it like teacher feedback, not to hide where it came from.
"""

with gr.Blocks(title="Red-Ink Grader") as demo:
    gr.Markdown("# Red-Ink Grader\nUpload an answer sheet and get it back marked, with marks a student can check and feedback they can act on.")
    with gr.Tab("Mark a sheet"):
        with gr.Row():
            sheet_in = gr.File(label="Answer sheet (PDF, photo or .txt)", type="filepath")
            spec_in = gr.File(label="Exam spec (YAML/JSON). Empty = sample quiz", file_types=[".yaml", ".yml", ".json"], type="filepath")
        with gr.Row():
            grader_in = gr.Radio(["LLM grader", "Lexical baseline"], value="LLM grader", label="Grader")
            input_in = gr.Radio(list(INPUTS), value="OCR text", label="What the grader reads")
            two_in = gr.Checkbox(value=True, label="Two-sided review (critic + advocate)")
            lang_in = gr.Dropdown(LANGUAGES, value="English", label="Feedback language")
        go = gr.Button("Mark it", variant="primary")
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
        gr.Examples([[str(SAMPLE / "answer_sheets" / f"S00{i}.txt")] for i in (1, 2, 3)], inputs=[sheet_in], label="Sample sheets")
        go.click(do_mark, [spec_in, sheet_in, grader_in, input_in, two_in, lang_in], [gallery, summary, pdf, report, crit_in])
        rg.click(do_regrade, [crit_in, reason_in], [rg_out])
    with gr.Tab("Mark a class"):
        with gr.Row():
            files_in = gr.File(label="Answer sheets", file_count="multiple", type="filepath")
            cspec_in = gr.File(label="Exam spec. Empty = sample quiz", file_types=[".yaml", ".yml", ".json"], type="filepath")
        with gr.Row():
            cgrader_in = gr.Radio(["LLM grader", "Lexical baseline"], value="LLM grader", label="Grader")
            ctwo_in = gr.Checkbox(value=True, label="Two-sided review")
        cgo = gr.Button("Mark the class", variant="primary")
        cnotes = gr.Markdown()
        czip = gr.File(label="Marked sheets, grades and report (zip)")
        creport = gr.HTML()
        cgo.click(do_class, [cspec_in, files_in, cgrader_in, ctwo_in], [creport, czip, cnotes])
    with gr.Tab("How it works"):
        gr.Markdown(ABOUT)

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2).launch(
        server_name=os.getenv("HOST", "0.0.0.0"), server_port=int(os.getenv("PORT", "7860")), show_error=True
    )
