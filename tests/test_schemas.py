import pytest
from pydantic import ValidationError

from autoassess.schemas import ExamSpec, Question


def _q(**over):
    base = dict(
        id="Q1",
        text="t",
        max_marks=3,
        criteria=[
            {"id": "Q1.c1", "description": "Names the three parts.", "marks": 2},
            {"id": "Q1.c2", "description": "Gives one example.", "marks": 1},
        ],
    )
    base.update(over)
    return base


def test_criteria_must_sum_to_max_marks():
    with pytest.raises(ValidationError, match="add up to 3 marks but the question is worth 4"):
        Question.model_validate(_q(max_marks=4))


def test_duplicate_criterion_ids_rejected():
    crit = [{"id": "Q1.c1", "description": "a b c d", "marks": 1}] * 3
    with pytest.raises(ValidationError, match="duplicate criterion ids"):
        Question.model_validate(_q(criteria=crit))


def test_duplicate_question_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate question ids"):
        ExamSpec.model_validate({"exam_id": "e", "title": "t", "questions": [_q(), _q()]})


def test_fractional_marks_sum():
    crit = [{"id": f"Q1.c{i}", "description": "x y z w", "marks": m} for i, m in enumerate([1.25, 1.25, 1.5])]
    assert Question.model_validate(_q(max_marks=4, criteria=crit)).max_marks == 4
