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
    allow_partial: bool = Field(default=True, description="Whether part of this criterion's marks can be awarded.")
    follow_through: bool = Field(
        default=False,
        description="Credit correct working that starts from the student's own earlier wrong value (ECF).",
    )

    @field_validator("description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("criterion description is empty")
        return v.strip()


class Question(BaseModel):
    """A question, its reference answer and the rubric that defines its marks."""

    id: str = Field(description="Label as printed on the paper, e.g. 'Q1' or 'Q3b'.")
    text: str
    max_marks: float = Field(gt=0)
    model_answer: str | None = None
    criteria: list[RubricCriterion] = Field(min_length=1)
    aliases: list[str] = Field(
        default_factory=list,
        description="Other labels students may write for this question, e.g. ['1', 'Ans 1'].",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Questions whose answers this one builds on; the grader sees the student's answers to them.",
    )
    marking: str | None = Field(
        default=None,
        description="Marking policy for this question, 'standard' or 'lenient'; defaults to the exam's.",
    )

    @model_validator(mode="after")
    def _criteria_sum_to_max(self) -> Question:
        total = sum(c.marks for c in self.criteria)
        if abs(total - self.max_marks) > MARK_TOLERANCE:
            raise ValueError(
                f"{self.id}: rubric criteria add up to {total:g} marks but the question is worth {self.max_marks:g}"
            )
        ids = [c.id for c in self.criteria]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"{self.id}: duplicate criterion ids {sorted(dupes)}")
        return self


MARKING_POLICIES = ("standard", "lenient")


class ExamSpec(BaseModel):
    """A validated collection of questions and a shared marking policy."""

    exam_id: str
    title: str
    language: str = Field(default="en", description="Main language of the paper (ISO 639-1).")
    marking: str = Field(
        default="standard",
        description="'standard': a criterion needs the idea stated. 'lenient': the idea in vague or "
        "imprecise words, or by clear implication, earns partial credit (a teacher's house style).",
    )
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def _marking_policy(self) -> ExamSpec:
        for q in [self, *self.questions]:
            if q.marking not in (None, *MARKING_POLICIES):
                raise ValueError(f"marking must be one of {MARKING_POLICIES}, not {q.marking!r}")
        for q in self.questions:
            if q.marking is None:
                q.marking = self.marking
        return self

    @model_validator(mode="after")
    def _unique_ids(self) -> ExamSpec:
        ids = [q.id for q in self.questions]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate question ids {sorted(dupes)}")
        return self

    @model_validator(mode="after")
    def _known_dependencies(self) -> ExamSpec:
        ids = {q.id for q in self.questions}
        for q in self.questions:
            unknown = [d for d in q.depends_on if d not in ids or d == q.id]
            if unknown:
                raise ValueError(f"{q.id}: depends_on names unknown questions {unknown}")
        return self

    @property
    def total_marks(self) -> float:
        """Sum the maximum marks across the exam's questions."""
        return sum(q.max_marks for q in self.questions)

    def question(self, qid: str) -> Question:
        """Look up a question by ID, raising KeyError when absent."""
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
    """Recognised text with optional geometry, confidence and block type."""

    text: str
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    kind: str = Field(default="text", description="text | equation | diagram")


class OCRPage(BaseModel):
    """A recognised page with source image metadata and ordered lines."""

    page_index: int = Field(ge=0)
    image_path: str | None = None
    lines: list[OCRLine] = Field(default_factory=list)
    provider: str = ""

    @property
    def text(self) -> str:
        """Join recognised lines in their stored reading order."""
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


class Verdict(str, Enum):  # noqa: UP042 - preserve the public Enum string representation
    """The criterion-level outcome: met, partial or not met."""

    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"


class CriterionResult(BaseModel):
    """A bounded criterion award with evidence, reasoning and review tags."""

    criterion_id: str
    verdict: Verdict
    marks_awarded: float = Field(ge=0)
    evidence: str | None = Field(
        default=None, description="Verbatim quote from the student's answer supporting the verdict."
    )
    reason: str
    tags: list[str] = Field(
        default_factory=list,
        description="How the mark was reached: ecf (follow-through), advocate (raised for missed credit), "
        "bod (benefit of the doubt), critic (lowered on audit), withdrawn (quote not found), fuzzy_quote.",
    )


class FeedbackItem(BaseModel):
    """An earned or lost rubric point with actionable guidance."""

    criterion_id: str
    kind: str = Field(description="earned | lost")
    text: str
    next_step: str | None = None


class Remark(BaseModel):
    """The short margin remark: one strength, one fix, one thing to do next time."""

    strength: str = ""
    fix: str = ""
    next_step: str = ""

    def lines(self) -> list[str]:
        """Format the strength, correction and next-step remark lines."""
        out = []
        if self.strength:
            out.append(f"Well done: {self.strength}")
        if self.fix:
            out.append(f"Fix: {self.fix}")
        if self.next_step:
            out.append(f"Next time: {self.next_step}")
        return out


class ErrorMark(BaseModel):
    """A wrong statement in the answer: wavy-underlined on the sheet, with a short correction."""

    quote: str
    correction: str = ""


class QuestionFeedback(BaseModel):
    """Verified feedback and annotation suggestions for one question."""

    question_id: str
    items: list[FeedbackItem]
    summary: str = ""
    remark: Remark | None = None
    errors: list[ErrorMark] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    def render(self) -> str:
        # Comments before the number: marks next to comments blunt the comments (Butler 1988).
        """Render earned credit and actionable deductions as plain text."""
        lines = self.remark.lines() if self.remark else []
        earned = [i for i in self.items if i.kind == "earned"]
        lost = [i for i in self.items if i.kind == "lost"]
        if earned:
            lines.append("What earned marks:")
            lines += [f"- {i.text}" for i in earned]
        if lost:
            lines.append("Where marks were lost:")
            lines += [f"- {i.text} Next time: {i.next_step}" if i.next_step else f"- {i.text}" for i in lost]
        if self.summary:
            lines.append(self.summary)
        return "\n".join(lines)


class QuestionGrade(BaseModel):
    """Criterion awards, feedback and confidence signals for one question."""

    question_id: str
    marks_awarded: float = Field(ge=0)
    max_marks: float = Field(gt=0)
    criteria: list[CriterionResult]
    feedback: str = ""
    feedback_items: list[FeedbackItem] = Field(default_factory=list)
    remark: Remark | None = None
    errors: list[ErrorMark] = Field(default_factory=list)
    feedback_en: str = Field(default="", description="English original when feedback was translated.")
    confidence: float = Field(default=1.0, ge=0, le=1)
    confidence_signals: dict[str, float] = Field(
        default_factory=dict, description="Each signal in [0, 1]; confidence is the lowest of them."
    )
    needs_review: bool = Field(default=False, description="Marked '?' on the sheet and queued for a human.")
    flags: list[str] = Field(default_factory=list)


class SheetGrade(BaseModel):
    """All question grades and feedback for one student's sheet."""

    exam_id: str
    student_id: str
    questions: list[QuestionGrade]
    summary_feedback: str = ""
    summary_feedback_en: str = ""
    feedback_language: str = "en"

    @property
    def total(self) -> float:
        """Sum the marks awarded across all questions."""
        return sum(q.marks_awarded for q in self.questions)
