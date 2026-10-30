"""Selective auto-marking coverage table from saved grades and human marks (synthetic fixture)."""

import csv
import json

from conftest import SAMPLE

from autoassess.cli import main
from autoassess.coverage import answer_rows, coverage_table, headline
from autoassess.schemas import CriterionResult, QuestionGrade, SheetGrade, Verdict
from autoassess.spec_builder import load_spec

SPEC = load_spec(SAMPLE / "exam_spec.yaml")


def synthetic(tmp_path):
    """Confident answers agree with the human; unsure or flagged ones are off by two marks."""
    grades_dir = tmp_path / "grades"
    grades_dir.mkdir()
    human = []
    for s in range(10):
        sid = f"S{s:03}"
        questions = []
        for i, q in enumerate(SPEC.questions):
            truth = float((s + i) % int(q.max_marks + 1))
            confident = (s + i) % 4 != 0
            flagged = s == 9 and i == 0
            marks = truth if confident and not flagged else min(q.max_marks, truth + 2)
            c = q.criteria[0]
            questions.append(
                QuestionGrade(
                    question_id=q.id,
                    marks_awarded=marks,
                    max_marks=q.max_marks,
                    criteria=[
                        CriterionResult(
                            criterion_id=c.id,
                            verdict=Verdict.PARTIAL,
                            marks_awarded=min(c.marks, marks),
                            reason="synthetic",
                        )
                    ],
                    confidence=0.95 if confident else 0.55,
                    flags=["possible_prompt_injection"] if flagged else [],
                )
            )
            for grader, delta in (("A", 0.0), ("B", 0.0)):
                human.append(
                    {
                        "exam_id": SPEC.exam_id,
                        "student_id": sid,
                        "grader": grader,
                        "question_id": q.id,
                        "criterion_id": c.id,
                        "marks_awarded": truth + delta,
                        "note": "",
                    }
                )
        (grades_dir / f"{sid}.json").write_text(
            SheetGrade(exam_id=SPEC.exam_id, student_id=sid, questions=questions).model_dump_json()
        )
    path = tmp_path / "human.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(human[0]))
        writer.writeheader()
        writer.writerows(human)
    return grades_dir, path


def test_coverage_table_separates_confident_answers(tmp_path):
    from autoassess.evaluate import load_grades, load_human_marks

    grades, human = synthetic(tmp_path)
    rows = answer_rows(SPEC, load_grades(grades), load_human_marks(human))
    assert len(rows) == 10 * len(SPEC.questions) and sum(r["flagged"] for r in rows) == 1
    table = {r["threshold"]: r for r in coverage_table(rows, (0.0, 0.8, 0.99))}
    assert table[0.0]["auto_n"] == len(rows) - 1 and table[0.0]["qwk"] < 1
    confident = sum(r["confidence"] >= 0.8 and not r["flagged"] for r in rows)
    assert table[0.8]["auto_n"] == confident and table[0.8]["review_n"] == len(rows) - confident
    assert table[0.8]["qwk"] == 1.0 and table[0.8]["mae"] == 0 and table[0.8]["bias"] == 0
    assert table[0.99]["auto_n"] == 0 and table[0.99]["qwk"] is None
    line = headline(list(table.values()))
    assert (
        line.startswith(f"At confidence >= 0.8: auto-mark {confident / len(rows):.0%} of answers")
        and "QWK 1.000" in line
    )


def test_coverage_cli_writes_table_and_figure(tmp_path, capsys):
    grades, human = synthetic(tmp_path)
    out = tmp_path / "coverage"
    assert (
        main(
            [
                "coverage",
                "--spec",
                str(SAMPLE / "exam_spec.yaml"),
                "--grades",
                str(grades),
                "--human",
                str(human),
                "--out",
                str(out),
                "--source",
                "synthetic fixture",
            ]
        )
        == 0
    )
    assert "auto-mark" in capsys.readouterr().out
    report = json.loads((out / "coverage.json").read_text())
    assert report["source"] == "synthetic fixture" and len(report["rows"]) == 10
    assert report["rows"][5]["threshold"] == 0.8 and report["rows"][5]["qwk_ci95"] is not None
    md = (out / "coverage.md").read_text()
    assert "| Confidence >= | Auto-marked |" in md and report["headline"] in md
    assert (out / "coverage.csv").read_text().startswith("threshold,auto_n,auto_share")
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        assert not (out / "coverage.png").exists()
    else:
        assert (out / "coverage.png").stat().st_size > 1000


def test_coverage_cli_refuses_unmatched_marks(tmp_path, capsys):
    grades, _ = synthetic(tmp_path)
    empty = tmp_path / "none.csv"
    empty.write_text("exam_id,student_id,grader,question_id,criterion_id,marks_awarded,note\n")
    assert (
        main(
            [
                "coverage",
                "--spec",
                str(SAMPLE / "exam_spec.yaml"),
                "--grades",
                str(grades),
                "--human",
                str(empty),
                "--out",
                str(tmp_path / "o"),
                "--no-ci",
            ]
        )
        == 2
    )
    assert "human mark" in capsys.readouterr().err
