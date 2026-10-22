"""Typed contracts between pipeline stages.

Every stage reads and writes one of these models as JSON, so stages can be
tested, cached and swapped independently.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

MARK_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Exam spec (built once per exam from the teacher's documents)
# ---------------------------------------------------------------------------


class RubricCriterion(BaseModel):
    """One checkable thing a grader awards marks for."""

    id: str = Field(description="Stable id, e.g. 'Q1.c2'.")
    description: str = Field(description="What the answer must show to earn these marks.")
    marks: float = Field(gt=0)
    allow_partial: bool = Field(
        default=True, description="Whether part of this criterion's marks can be awarded."
    )

    @field_validator("description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("criterion description is empty")
        return v.strip()


class Question(BaseModel):
    id: str = Field(description="Label as printed on the paper, e.g. 'Q1' or 'Q3b'.")
    text: str
    max_marks: float = Field(gt=0)
    model_answer: str | None = None
    criteria: list[RubricCriterion] = Field(min_length=1)
    aliases: list[str] = Field(
        default_factory=list,
        description="Other labels students may write for this question, e.g. ['1', 'Ans 1'].",
    )

    @model_validator(mode="after")
    def _criteria_sum_to_max(self) -> Question:
        total = sum(c.marks for c in self.criteria)
        if abs(total - self.max_marks) > MARK_TOLERANCE:
            raise ValueError(
                f"{self.id}: rubric criteria add up to {total:g} marks "
                f"but the question is worth {self.max_marks:g}"
            )
        ids = [c.id for c in self.criteria]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"{self.id}: duplicate criterion ids {sorted(dupes)}")
        return self


class ExamSpec(BaseModel):
    exam_id: str
    title: str
    language: str = Field(default="en", description="Main language of the paper (ISO 639-1).")
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> ExamSpec:
        ids = [q.id for q in self.questions]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate question ids {sorted(dupes)}")
        return self

    @property
    def total_marks(self) -> float:
        return sum(q.max_marks for q in self.questions)

    def question(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise KeyError(qid)


# ---------------------------------------------------------------------------
# Answer sheet side
# ---------------------------------------------------------------------------


class BBox(BaseModel):
    """Pixel box on a page image: (x0, y0) top-left, (x1, y1) bottom-right."""

    x0: float
    y0: float
    x1: float
    y1: float


class OCRLine(BaseModel):
    text: str
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    kind: str = Field(default="text", description="text | equation | diagram")


class OCRPage(BaseModel):
    page_index: int = Field(ge=0)
    image_path: str | None = None
    lines: list[OCRLine] = Field(default_factory=list)
    provider: str = ""

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


class AnswerSegment(BaseModel):
    """The part of a sheet that answers one question (may span pages)."""

    question_id: str
    text: str
    pages: list[int] = Field(default_factory=list)
    lines: list[OCRLine] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Grading output
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"


class CriterionResult(BaseModel):
    criterion_id: str
    verdict: Verdict
    marks_awarded: float = Field(ge=0)
    evidence: str | None = Field(
        default=None, description="Verbatim quote from the student's answer supporting the verdict."
    )
    reason: str


class FeedbackItem(BaseModel):
    criterion_id: str
    kind: str = Field(description="earned | lost")
    text: str
    next_step: str | None = None


class QuestionFeedback(BaseModel):
    question_id: str
    items: list[FeedbackItem]
    summary: str = ""
    flags: list[str] = Field(default_factory=list)

    def render(self) -> str:
        lines = [self.summary] if self.summary else []
        earned = [i for i in self.items if i.kind == "earned"]
        lost = [i for i in self.items if i.kind == "lost"]
        if earned:
            lines.append("What earned marks:")
            lines += [f"- {i.text}" for i in earned]
        if lost:
            lines.append("Where marks were lost:")
            lines += [f"- {i.text} Next time: {i.next_step}" if i.next_step else f"- {i.text}" for i in lost]
        return "\n".join(lines)


class QuestionGrade(BaseModel):
    question_id: str
    marks_awarded: float = Field(ge=0)
    max_marks: float = Field(gt=0)
    criteria: list[CriterionResult]
    feedback: str = ""
    feedback_items: list[FeedbackItem] = Field(default_factory=list)
    feedback_en: str = Field(default="", description="English original when feedback was translated.")
    confidence: float = Field(default=1.0, ge=0, le=1)
    flags: list[str] = Field(default_factory=list)


class SheetGrade(BaseModel):
    exam_id: str
    student_id: str
    questions: list[QuestionGrade]
    summary_feedback: str = ""
    summary_feedback_en: str = ""
    feedback_language: str = "en"

    @property
    def total(self) -> float:
        return sum(q.marks_awarded for q in self.questions)
