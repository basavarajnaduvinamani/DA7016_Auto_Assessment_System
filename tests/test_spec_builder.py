import pytest
from conftest import FakeLLM
from pydantic import ValidationError

from autoassess.cli import main
from autoassess.spec_builder import draft_spec, lint_spec, load_spec, save_spec


def test_sample_spec_loads(sample_spec_path):
    spec = load_spec(sample_spec_path)
    assert [q.id for q in spec.questions] == ["Q1", "Q2", "Q3"]
    assert spec.total_marks == 15


def test_round_trip_yaml_and_json(sample_spec_path, tmp_path):
    spec = load_spec(sample_spec_path)
    for name in ("s.yaml", "s.json"):
        save_spec(spec, tmp_path / name)
        assert load_spec(tmp_path / name) == spec


def test_lint_flags_vague_and_short_criteria():
    from autoassess.schemas import ExamSpec

    spec = ExamSpec.model_validate(
        {
            "exam_id": "e",
            "title": "t",
            "questions": [
                {
                    "id": "Q1",
                    "text": "t",
                    "max_marks": 5,
                    "criteria": [
                        {"id": "Q1.c1", "description": "Good explanation", "marks": 1},
                        {"id": "Q1.c2", "description": "Explains the idea clearly and well", "marks": 1},
                        {
                            "id": "Q1.c3",
                            "description": "Derives the full closed-form expression for the gradient",
                            "marks": 3,
                            "allow_partial": False,
                        },
                    ],
                }
            ],
        }
    )
    warnings = "\n".join(lint_spec(spec))
    assert "Q1: no model answer" in warnings
    assert "Q1.c1: description is very short" in warnings
    assert "Q1.c2: vague wording" in warnings
    assert "Q1.c3: 3 marks all-or-nothing" in warnings


def test_sample_spec_has_no_vague_criteria(sample_spec_path):
    assert lint_spec(load_spec(sample_spec_path)) == []


GOOD = {
    "exam_id": "e",
    "title": "t",
    "questions": [
        {
            "id": "Q1",
            "text": "t",
            "max_marks": 2,
            "criteria": [{"id": "Q1.c1", "description": "States the definition of entropy.", "marks": 2}],
        }
    ],
}
BAD = {**GOOD, "questions": [{**GOOD["questions"][0], "max_marks": 3}]}


def test_draft_spec_repairs_once_with_validation_error():
    llm = FakeLLM([BAD, GOOD])
    spec = draft_spec("paper", "rubric", "answers", llm)
    assert spec.questions[0].max_marks == 2
    assert len(llm.calls) == 2
    assert "add up to 2 marks but the question is worth 3" in llm.calls[1][1]


def test_draft_spec_gives_up_after_repairs():
    with pytest.raises(ValidationError):
        draft_spec("p", "r", "a", FakeLLM([BAD, BAD]))


def test_cli_validate_spec(sample_spec_path, capsys):
    assert main(["validate-spec", str(sample_spec_path)]) == 0
    assert "OK da7016-sample: 3 questions, 15 marks" in capsys.readouterr().out


def test_cli_grade_baseline_and_evaluate(sample_spec_path, tmp_path, capsys):
    from conftest import SAMPLE

    sheets = [str(SAMPLE / "answer_sheets" / f"S00{i}.txt") for i in (1, 2, 3)]
    out = tmp_path / "grades"
    assert main(["grade", "--spec", str(sample_spec_path), "--out", str(out), "--baseline", *sheets]) == 0
    assert sorted(p.name for p in out.glob("*.json")) == ["S001.json", "S002.json", "S003.json"]
    assert "<mark" in (out / "S001.html").read_text()
    human = tmp_path / "human.csv"
    rows = ["exam_id,student_id,grader,question_id,criterion_id,marks_awarded,note"]
    for g, bump in (("A", 0), ("B", 0.5)):
        for sid, marks in (("S001", [5, 4, 5]), ("S002", [2, 1, 2]), ("S003", [0, 0.5, 0])):
            rows += [f"e,{sid},{g},Q{i + 1},Q{i + 1}.c1,{m + bump if m else m}," for i, m in enumerate(marks)]
    human.write_text("\n".join(rows))
    assert main(["evaluate", "--spec", str(sample_spec_path), "--grades", str(out), "--human", str(human)]) == 0
    text = capsys.readouterr().out
    assert '"human_vs_human"' in text and '"qwk"' in text
