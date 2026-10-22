"""HTTP API: one /grade endpoint taking the exam spec and an answer sheet.

Run with:  uvicorn autoassess.api:app --reload
Needs the 'api' extras: pip install -e ".[api,ingest]"
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from autoassess import __version__
from autoassess.config import Settings
from autoassess.pipeline import read_sheet, run
from autoassess.providers import make_llm, make_ocr, make_translator
from autoassess.schemas import ExamSpec

app = FastAPI(title="Auto-Assessment", version=__version__, description="Rubric-grounded grading with evidence-linked feedback.")


@app.get("/health")
def health() -> dict:
    s = Settings.load()
    return {"status": "ok", "version": __version__, "ocr": s.ocr_provider, "llm_configured": bool(s.llm_model)}


@app.post("/grade")
async def grade(
    spec: UploadFile = File(..., description="Exam spec, YAML or JSON"),
    sheet: UploadFile = File(..., description="Answer sheet: .txt, .pdf or an image"),
    student_id: str = Form("student"),
    mode: str = Form("llm", description="llm | baseline"),
    runs: int = Form(3),
    critic: bool = Form(False),
    feedback_language: str | None = Form(None),
) -> dict:
    try:
        exam = ExamSpec.model_validate(yaml.safe_load(await spec.read()))
    except (ValidationError, yaml.YAMLError) as err:
        raise HTTPException(status_code=422, detail=f"invalid exam spec: {err}") from err

    settings = Settings.load()
    if mode == "llm" and not settings.llm_model:
        raise HTTPException(status_code=400, detail="no LLM configured (AUTOASSESS_LLM_MODEL); use mode=baseline")
    llm = make_llm(settings) if mode == "llm" else None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(sheet.filename or "sheet.txt").name
        path.write_bytes(await sheet.read())
        pages = read_sheet(path, make_ocr(settings), work_dir=Path(tmp) / "pages", language=exam.language)
        result = run(
            exam,
            pages,
            student_id,
            llm,
            runs=runs,
            critic=make_llm(settings, critic=True) if critic and llm else None,
            translator=make_translator(settings) if feedback_language else None,
            feedback_language=feedback_language,
        )
        html = result.html()  # page images are embedded before the temp dir goes away
    return {"grade": result.grade.model_dump(mode="json"), "html": html}
