"""Exercise anonymised export and reject silently changed public score evidence."""

import csv
import json
import subprocess
import sys
from pathlib import Path

from autoassess.schemas import QuestionGrade, SheetGrade

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "scripts/study.py"


def _run(*args):
    return subprocess.run([sys.executable, str(STUDY), *map(str, args)], capture_output=True, text=True, cwd=ROOT)


def test_export_removes_answers_names_and_feedback_and_rejects_missing_scores(tmp_path):
    dataset, grades, output = [tmp_path / name for name in ("dataset", "grades", "out")]
    dataset.mkdir()
    grades.mkdir()
    (dataset / "exam_spec.yaml").write_text("private rubric placeholder\n")
    with (dataset / "sheets.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["student_id", "split"])
        w.writerows([["PRIVATE-NAME-1", "dev"], ["PRIVATE-NAME-2", "test"]])
    with (dataset / "human_marks.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["student_id", "grader", "question_id", "marks_awarded"])
        for i in (1, 2):
            for grader in ("grader_A", "grader_B"):
                w.writerow([f"PRIVATE-NAME-{i}", grader, f"Q{i}", 1])
    for i in (1, 2):
        grade = SheetGrade(
            exam_id="private-exam",
            student_id=f"PRIVATE-NAME-{i}",
            questions=[
                QuestionGrade(question_id=f"Q{i}", marks_awarded=1, max_marks=5, criteria=[], feedback="PRIVATE-ANSWER")
            ],
        )
        (grades / f"PRIVATE-NAME-{i}.json").write_text(grade.model_dump_json())
    args = (
        "export",
        "--dataset",
        dataset,
        "--grades",
        grades,
        "--out",
        output,
        "--label",
        "test fixture",
        "--key-file",
        tmp_path / "private-key",
    )
    run = _run(*args)
    assert run.returncode == 0, run.stderr
    for p in output.iterdir():
        assert "PRIVATE-NAME" not in p.read_text()
        assert "PRIVATE-ANSWER" not in p.read_text()
    scores = json.loads((output / "scores.json").read_text())
    assert len(scores) == 2
    assert all(len(r["item_id"]) == 64 and len(r["question_id"]) == 64 for r in scores)
    aggregate = output / "aggregate.json"
    assert _run("aggregate", "--scores", output / "scores.json", "--out", aggregate).returncode == 0
    assert (
        _run(
            "aggregate", "--scores", output / "scores.json", "--out", output / "rerun.json", "--assert-equal", aggregate
        ).returncode
        == 0
    )
    scores[0]["system"] = 0
    (output / "scores.json").write_text(json.dumps(scores))
    assert (
        _run(
            "aggregate",
            "--scores",
            output / "scores.json",
            "--out",
            output / "changed.json",
            "--assert-equal",
            aggregate,
        ).returncode
        != 0
    )
    (grades / "PRIVATE-NAME-2.json").unlink()
    assert _run(*args).returncode != 0


def test_report_verification_fails_closed_for_missing_raw_evidence(tmp_path):
    result = _run("verify-numbers", "--out", tmp_path / "verification.json")
    assert result.returncode != 0
    output = json.loads((tmp_path / "verification.json").read_text())
    assert output["status"] == "BLOCKED"
    assert output["literals"]
    assert all(r["status"].startswith("UNKNOWN") for r in output["literals"])
