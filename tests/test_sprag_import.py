"""Exercise SPRAG import and the unchanged evaluation commands on invented data."""

import csv
import json
import shutil
import socket
from collections import defaultdict
from pathlib import Path

import pytest

from autoassess.cli import main
from autoassess.datasets.sprag import HOLISTIC, import_sprag
from autoassess.evaluate import compare, load_human_marks, load_sheet_meta
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.segment import segment
from autoassess.spec_builder import load_spec

FIXTURE = Path(__file__).parent / "fixtures" / "sprag"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("SPRAG importer tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def rows(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def files(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_spec_sheets_and_human_marks_round_trip(tmp_path, capsys):
    out = tmp_path / "imported"
    assert main(["import-sprag", "--src", str(FIXTURE), "--out", str(out), "--per-question", "0"]) == 0
    summary = capsys.readouterr().out
    assert len(summary.splitlines()) == 1
    assert "6 questions, 20 answers" in summary and "4 missing scores" in summary
    assert "dev/test:" in summary
    spec = load_spec(out / "exam_spec.yaml")
    assert main(["validate-spec", str(out / "exam_spec.yaml")]) == 0
    assert spec.exam_id == "sprag-all"
    catalog = {r["QuestionID"]: r for r in rows(FIXTURE / "Question_data.csv")}
    source = defaultdict(list)
    for filename in ("MLResponses.csv", "PyResponses.csv"):
        for row in rows(FIXTURE / filename):
            source[row["QuestionID"]].append(row)
    human = load_human_marks(out / "human_marks.csv")
    meta = load_sheet_meta(out / "sheets.csv")
    assert len(meta) == 20
    assert len(rows(out / "human_marks.csv")) == 36
    assert set(human) == {"grader_A", "grader_B"}
    for i, question in enumerate(spec.questions, 1):
        assert question.id == f"Q{i}"
        source_id = question.aliases[0]
        assert source_id == sorted(catalog)[i - 1]
        assert question.text == catalog[source_id]["QuestionText"]
        assert question.model_answer == catalog[source_id]["Reference Answer"]
        assert question.max_marks == 5 and len(question.criteria) == 1
        criterion = question.criteria[0]
        assert criterion.id == f"Q{i}.c1" and criterion.marks == 5
        assert criterion.description == HOLISTIC and criterion.allow_partial
        for ordinal, original in enumerate(source[source_id], 1):
            sid = f"{source_id}-{ordinal:04d}"
            path = out / "sheets" / f"{sid}.txt"
            answers = segment(spec, [PlainTextOCR().read_page(path)])
            assert answers[question.id].text == original["StudentAnswer"]
            assert all(not answer.text for qid, answer in answers.items() if qid != question.id)
            assert meta[sid]["question_type"] == catalog[source_id]["QuestionType"]
            assert meta[sid]["subject"] == ("ml" if source_id.startswith("BasicML") else "python")
            for grader, field in (("grader_A", "Score1"), ("grader_B", "Score2")):
                key = (sid, question.id)
                if original[field]:
                    assert human[grader][key] == float(original[field])
                else:
                    assert key not in human[grader]
    assert "-" in (out / "sheets/BasicML010-0003.txt").read_text()
    assert "No answer for this" in (out / "sheets/BasicML020-0003.txt").read_text()
    # compare uses independent raw scores even without a system grade collection.
    report = compare(spec, [], human)
    assert report["human_vs_human"]["n"] == 17


def test_baseline_evaluate_and_results_end_to_end(tmp_path, monkeypatch):
    from autoassess import providers

    monkeypatch.setattr(providers, "make_llm", lambda *a, **k: pytest.fail("Baseline must not construct an LLM"))
    out, grades, pack = tmp_path / "imported", tmp_path / "grades", tmp_path / "pack"
    import_sprag(FIXTURE, out, per_question=0)
    spec = str(out / "exam_spec.yaml")
    sheets = sorted(str(path) for path in (out / "sheets").glob("*.txt"))
    assert main(["grade", "--baseline", "--spec", spec, "--out", str(grades), *sheets]) == 0
    agreement = tmp_path / "agreement.json"
    assert main(["evaluate", "--spec", spec, "--grades", str(grades), "--human", str(out / "human_marks.csv"),
                 "--meta", str(out / "sheets.csv"), "--out", str(agreement)]) == 0
    report = json.loads(agreement.read_text())
    assert report["human_vs_human"]["n"] == 17
    assert report["vs_consensus"]["n"] == 19
    assert set(report["per_grader"]) == {"grader_A", "grader_B"}
    assert "subject" in report["per_group"] and "split" in report["per_group"]
    assert main(["results", "--agreement", str(agreement), "--out", str(pack)]) == 0
    assert (pack / "tables/agreement.tex").is_file()
    assert json.loads((pack / "summary.json").read_text())["human_qwk"] == report["human_vs_human"]["qwk"]


def test_deterministic_stratified_sampling_and_question_split(tmp_path):
    first, second, changed = [tmp_path / name for name in ("first", "second", "changed")]
    stats = import_sprag(FIXTURE, first, per_question=2, dev_share=0.5, seed=7)
    assert stats.questions == 6 and stats.answers == 12
    assert stats.dev_questions == stats.test_questions == 3
    import_sprag(FIXTURE, second, per_question=2, dev_share=0.5, seed=7)
    assert files(first) == files(second)
    import_sprag(FIXTURE, changed, per_question=2, dev_share=0.5, seed=0)
    assert (first / "sheets.csv").read_bytes() != (changed / "sheets.csv").read_bytes()
    split = defaultdict(set)
    for sid, info in load_sheet_meta(first / "sheets.csv").items():
        split[sid.rsplit("-", 1)[0]].add(info["split"])
    assert all(len(parts) == 1 for parts in split.values())
    # First invented question has low, middle and high scores: retain both extremes.
    names = {path.name for path in (first / "sheets").glob("*.txt")}
    assert {"BasicML010-0001.txt", "BasicML010-0003.txt"} <= names


@pytest.mark.parametrize("subject", ["ml", "python"])
def test_subject_filter_and_stable_source_ids(tmp_path, subject):
    all_out, part = tmp_path / "all", tmp_path / "part"
    import_sprag(FIXTURE, all_out, per_question=0)
    stats = import_sprag(FIXTURE, part, subject=subject)
    assert stats.questions == 3 and stats.answers == 10
    assert load_spec(part / "exam_spec.yaml").exam_id == f"sprag-{subject}"
    assert {info["subject"] for info in load_sheet_meta(part / "sheets.csv").values()} == {subject}
    for path in (part / "sheets").glob("*.txt"):
        # IDs refer to original rows, not to the sampled/renumbered output.
        assert (all_out / "sheets" / path.name).is_file()
        assert path.read_text().splitlines()[1:] == (all_out / "sheets" / path.name).read_text().splitlines()[1:]


def test_large_exam_uses_recognizable_aliases_without_changing_segmenter(tmp_path):
    source, out = tmp_path / "source", tmp_path / "out"
    source.mkdir()
    questions = [(f"BasicML{i:03d}", f"Invented fruit question {i}", "Explain", "A measured fruit feature.") for i in range(1, 115)]
    with (source / "Question_data.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["QuestionID", "QuestionText", "QuestionType", "Reference Answer"])
        writer.writerows(questions)
    with (source / "MLResponses.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["QuestionID", "StudentAnswer", "Score1", "Score2"])
        writer.writerows((qid, "A measured fruit feature.", "5", "5") for qid, *_ in questions)
    import_sprag(source, out, subject="ml")
    spec = load_spec(out / "exam_spec.yaml")
    assert len(spec.questions) == 114
    for q in spec.questions:
        path = out / "sheets" / f"{q.aliases[0]}-0001.txt"
        answers = segment(spec, [PlainTextOCR().read_page(path)])
        assert answers[q.id].text == "A measured fruit feature."
        assert sum(bool(a.text) for a in answers.values()) == 1


@pytest.mark.parametrize("kwargs", [{"per_question": -1}, {"dev_share": -0.1}, {"dev_share": 1.1},
                                    {"dev_share": float("nan")}, {"subject": "other"}])
def test_invalid_options_do_not_create_output(tmp_path, kwargs):
    with pytest.raises(ValueError):
        import_sprag(FIXTURE, tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("bad_score", ["nan", "inf", "-1", "6", "wrong"])
def test_invalid_scores_are_rejected_before_writing(tmp_path, bad_score):
    source, out = tmp_path / "source", tmp_path / "out"
    shutil.copytree(FIXTURE, source)
    path = source / "MLResponses.csv"
    data = rows(path)
    data[0]["Score1"] = bad_score
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    with pytest.raises(ValueError, match="score must"):
        import_sprag(source, out)
    assert not out.exists()


def test_existing_output_is_preserved_and_cli_reports_error(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("keep")
    assert main(["import-sprag", "--src", str(FIXTURE), "--out", str(out)]) == 2
    assert (out / "keep.txt").read_text() == "keep"
    assert "new or empty" in capsys.readouterr().err


def test_seed_controls_selection_within_score_strata(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    with (source / "MLResponses.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["QuestionID", "StudentAnswer", "Score1", "Score2"])
        writer.writerows(("BasicML010", f"Invented berry response {i}", score, score)
                         for score in (0, 5) for i in range(5))
    choices = set()
    for seed in range(5):
        out = tmp_path / f"sample-{seed}"
        import_sprag(source, out, subject="ml", per_question=2, seed=seed)
        choices.add(tuple(sorted(path.name for path in (out / "sheets").glob("*.txt"))))
        human = load_human_marks(out / "human_marks.csv")
        assert sorted(human["grader_A"].values()) == [0, 5]
    assert len(choices) > 1
