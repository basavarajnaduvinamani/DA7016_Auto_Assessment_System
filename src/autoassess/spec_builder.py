"""Exam spec builder: turn the teacher's documents into a validated ExamSpec.

Two routes:
- load_spec: read a hand-written YAML or JSON spec (the reliable route).
- draft_spec: ask an LLM to structure the question paper, rubric and model
  answers, validate the result, and feed validation errors back once.

lint_spec flags rubric problems before any grading: vague or very short
criteria, several things bundled into one criterion, large all-or-nothing
criteria, missing model answers, duplicate criteria, and follow-through
criteria on a question that builds on nothing. Rubric quality decides marks
more than model choice does, so a teacher should clear these first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from autoassess.providers.base import LLMClient
from autoassess.schemas import ExamSpec


def load_spec(path: str | Path) -> ExamSpec:
    """Load and validate an exam specification from YAML or JSON."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if path.suffix == ".json" else yaml.safe_load(raw)
    return ExamSpec.model_validate(data)


def save_spec(spec: ExamSpec, path: str | Path) -> None:
    """Write a validated exam specification as YAML or JSON."""
    path = Path(path)
    data = spec.model_dump(mode="json")
    if path.suffix == ".json":
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


DRAFT_SYSTEM = """You convert exam documents into a JSON exam spec for an automatic grader.
Return ONLY a JSON object with this shape:
{"exam_id": str, "title": str, "language": "en",
 "questions": [{"id": str, "text": str, "max_marks": number, "model_answer": str|null,
   "aliases": [str], "criteria": [{"id": str, "description": str, "marks": number, "allow_partial": bool}]}]}
Rules:
- One question per printed question or sub-part that carries its own marks; use the paper's labels (e.g. "Q1", "Q3b").
- aliases: other labels a student might write for it, e.g. ["1", "Ans 1", "1."].
- Criteria come from the rubric. Each describes ONE checkable thing, and criteria marks must add up to max_marks exactly.
- Criterion ids are "<question id>.c<n>".
- Copy the model answer verbatim when given; otherwise null.
- Do not invent marks or criteria that the rubric does not support."""


def _draft_prompt(paper: str, rubric: str, model_answers: str, exam_id: str) -> str:
    return (
        f"exam_id: {exam_id}\n\n"
        f"=== QUESTION PAPER ===\n{paper}\n\n"
        f"=== RUBRIC ===\n{rubric}\n\n"
        f"=== MODEL ANSWERS ===\n{model_answers}\n"
    )


def draft_spec(
    paper: str, rubric: str, model_answers: str, llm: LLMClient, exam_id: str = "exam", max_repairs: int = 1
) -> ExamSpec:
    """Draft an exam specification from teacher documents, repairing validation once."""
    user = _draft_prompt(paper, rubric, model_answers, exam_id)
    data = llm.complete_json(DRAFT_SYSTEM, user)
    for attempt in range(max_repairs + 1):
        try:
            return ExamSpec.model_validate(data)
        except ValidationError as err:
            if attempt == max_repairs:
                raise
            repair = (
                f"{user}\n\nYour previous spec:\n{json.dumps(data, ensure_ascii=False)}\n\n"
                f"It failed validation:\n{err}\n\nReturn a corrected spec."
            )
            data = llm.complete_json(DRAFT_SYSTEM, repair)
    raise AssertionError("unreachable")


_VAGUE = re.compile(
    r"\b(good|well|proper(ly)?|appropriate(ly)?|clear(ly)?|adequate(ly)?|overall|neat(ly)?|nice)\b", re.I
)


_BUNDLE = re.compile(r"\b(and|also|as well as|along with)\b|;", re.I)


def lint_spec(spec: ExamSpec) -> list[str]:
    """Warnings for criteria a grader cannot check reliably."""
    warnings: list[str] = []
    for q in spec.questions:
        if not q.model_answer:
            warnings.append(f"{q.id}: no model answer; grading leans entirely on the rubric")
        for c in q.criteria:
            words = len(c.description.split())
            if words < 4:
                warnings.append(f"{c.id}: description is very short ({words} words): {c.description!r}")
            elif _VAGUE.search(c.description) and words < 12:
                warnings.append(f"{c.id}: vague wording with no checkable condition: {c.description!r}")
            if not c.allow_partial and c.marks > 2:
                warnings.append(f"{c.id}: {c.marks:g} marks all-or-nothing; consider splitting it")
            if len(_BUNDLE.findall(c.description)) >= 3:
                warnings.append(f"{c.id}: bundles several checks into one criterion; split it so each can be marked")
            if c.follow_through and not q.depends_on:
                warnings.append(f"{c.id}: follow-through but {q.id} has no depends_on, so there is nothing to follow")
        descs = [c.description.lower().strip(" .") for c in q.criteria]
        for d in {d for d in descs if descs.count(d) > 1}:
            warnings.append(f"{q.id}: duplicate criterion {d!r}")
    return warnings
