"""Teacher-authored question/rubric form conversion."""

from __future__ import annotations

import uuid
from typing import Any

from starlette.datastructures import FormData

from autoassess.schemas import ExamSpec


def question_values(form: FormData, index: int) -> dict[str, Any]:
    """Collect one question and its repeated criterion fields from a form."""
    prefix = f"q{index}_"
    descriptions = form.getlist(prefix + "criterion_description")
    marks = form.getlist(prefix + "criterion_marks")
    return {
        "index": index,
        "text": str(form.get(prefix + "text", "")),
        "max_marks": str(form.get(prefix + "max_marks", "")),
        "model_answer": str(form.get(prefix + "model_answer", "")),
        "criteria": [{"description": d, "marks": m} for d, m in zip(descriptions, marks, strict=True)]
        or [{"description": "", "marks": ""}],
    }


def build_spec(title: str, values: list[dict[str, Any]]) -> ExamSpec:
    """Validate teacher-authored questions as a lenient exam specification."""
    questions = []
    for value in values:
        qid = f"Q{value['index']}"
        if not value["text"].strip():
            raise ValueError(f"Add question text for {qid}.")
        criteria = [
            {"id": f"{qid}.c{i}", "description": c["description"], "marks": float(c["marks"])}
            for i, c in enumerate(value["criteria"], 1)
            if c["description"].strip() or str(c["marks"]).strip()
        ]
        questions.append(
            {
                "id": qid,
                "text": value["text"].strip(),
                "max_marks": float(value["max_marks"]),
                "criteria": criteria,
                "model_answer": value["model_answer"].strip() or None,
            }
        )
    return ExamSpec(exam_id=f"exam-{uuid.uuid4().hex[:12]}", title=title, marking="lenient", questions=questions)
