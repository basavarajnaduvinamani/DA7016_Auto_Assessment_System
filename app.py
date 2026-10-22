"""Gradio demo: upload an exam spec and an answer sheet, get marks and feedback.

Run locally:      pip install -e ".[demo,ingest]" && python app.py
Hugging Face:     a Gradio Space runs app.py; set the AUTOASSESS_* and
                  BODHAN_* values as Space secrets.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr

from autoassess.config import Settings
from autoassess.pipeline import read_sheet, run
from autoassess.providers import make_llm, make_ocr
from autoassess.spec_builder import load_spec

SAMPLE = Path(__file__).parent / "data" / "sample_exam"


def grade(spec_file, sheet_file, mode, critic, runs):
    settings = Settings.load()
    spec = load_spec(spec_file or SAMPLE / "exam_spec.yaml")
    if sheet_file is None:
        raise gr.Error("Upload an answer sheet (.txt, .pdf or an image).")
    if mode == "LLM grader" and not settings.llm_model:
        raise gr.Error("No LLM is configured (AUTOASSESS_LLM_MODEL). Choose the lexical baseline or set one.")
    llm = make_llm(settings) if mode == "LLM grader" else None
    sheet = Path(sheet_file)
    with tempfile.TemporaryDirectory() as tmp:
        pages = read_sheet(sheet, make_ocr(settings), work_dir=Path(tmp), language=spec.language)
        result = run(
            spec,
            pages,
            sheet.stem,
            llm,
            runs=int(runs),
            critic=make_llm(settings, critic=True) if critic and llm else None,
        )
        html = result.html()
    out = Path(tempfile.mkdtemp()) / f"{sheet.stem}_report.html"
    out.write_text(html, encoding="utf-8")
    return html, result.grade.model_dump(mode="json"), str(out)


with gr.Blocks(title="Auto-Assessment") as demo:
    gr.Markdown(
        "# Auto-Assessment\nGrades an answer sheet against a rubric. Every mark quotes the student's own words, "
        "and feedback says what to write next time. Leave the spec empty to use the sample quiz."
    )
    with gr.Row():
        spec_in = gr.File(label="Exam spec (YAML or JSON)", file_types=[".yaml", ".yml", ".json"], type="filepath")
        sheet_in = gr.File(label="Answer sheet (.txt, .pdf, image)", type="filepath")
    with gr.Row():
        mode_in = gr.Radio(["LLM grader", "Lexical baseline"], value="LLM grader", label="Grader")
        critic_in = gr.Checkbox(label="Critic audits awarded marks", value=True)
        runs_in = gr.Slider(1, 5, value=3, step=1, label="Grading runs per question")
    go = gr.Button("Grade", variant="primary")
    report = gr.HTML()
    with gr.Accordion("Raw result", open=False):
        raw = gr.JSON()
    download = gr.File(label="Download report")
    gr.Examples(
        examples=[[str(SAMPLE / "exam_spec.yaml"), str(SAMPLE / "answer_sheets" / f"S00{i}.txt")] for i in (1, 2, 3)],
        inputs=[spec_in, sheet_in],
    )
    go.click(grade, [spec_in, sheet_in, mode_in, critic_in, runs_in], [report, raw, download])

if __name__ == "__main__":
    demo.launch()
