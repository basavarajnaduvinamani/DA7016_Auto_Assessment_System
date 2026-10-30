"""Bootstrap sampling preserves whole questions, including repeated draws."""

import random

import pytest
from conftest import SAMPLE

from autoassess.evaluate import compare
from autoassess.metrics import agreement_report, bootstrap_ci, mean_absolute_error, signed_bias
from autoassess.schemas import QuestionGrade, SheetGrade
from autoassess.spec_builder import load_spec


def test_correlated_questions_have_wider_cluster_interval():
    system = [x for x in range(5) for _ in range(20)]
    human = [0] * len(system)
    groups = [f"Q{x}" for x in range(5) for _ in range(20)]
    item = bootstrap_ci(system, human, mean_absolute_error)
    cluster = bootstrap_ci(system, human, mean_absolute_error, groups=groups)
    assert cluster[1] - cluster[0] > 2 * (item[1] - item[0])
    assert cluster == bootstrap_ci(system, human, mean_absolute_error, groups=groups)


def test_no_groups_preserves_original_item_sampling():
    system, human = [0, 1, 4, 2, 3], [1, 2, 2, 2, 5]
    rng = random.Random(7)
    stats = []
    for _ in range(100):
        idx = [rng.randrange(5) for _ in range(5)]
        stats.append(signed_bias([system[i] for i in idx], [human[i] for i in idx]))
    stats.sort()
    expected = (round(stats[int(0.025 * 99)], 3), round(stats[int(0.975 * 99)], 3))
    assert bootstrap_ci(system, human, signed_bias, n_boot=100, seed=7) == expected
    assert bootstrap_ci(system, human, signed_bias, n_boot=100, seed=7, groups=None) == expected
    assert agreement_report(system, human, ci=True)["ci_method"] == "item"


def test_cluster_draw_retains_all_members_and_duplicate_groups():
    draws = []

    def record(system, human):
        draws.append(system)
        assert human == [0] * len(system)
        assert system.count(1) == system.count(2)
        assert system.count(3) == system.count(4) == system.count(5)
        return sum(system) / len(system)

    bootstrap_ci([1, 2, 3, 4, 5], [0] * 5, record, n_boot=30, groups=["A", "A", "B", "B", "B"])
    assert [1, 2, 1, 2] in draws and [3, 4, 5, 3, 4, 5] in draws


@pytest.mark.parametrize("human,groups", [([1], ["Q1", "Q1"]), ([1, 2], ["Q1"])])
def test_misaligned_groups_rejected(human, groups):
    with pytest.raises(ValueError, match="equal lengths"):
        bootstrap_ci([1, 2], human, mean_absolute_error, groups=groups)


def test_evaluation_clusters_consensus_and_metadata_groups():
    spec = load_spec(SAMPLE / "exam_spec.yaml")
    grades = [
        SheetGrade(
            exam_id=spec.exam_id,
            student_id=f"S{i}",
            questions=[
                QuestionGrade(question_id=q.id, max_marks=q.max_marks, marks_awarded=float(i % 3), criteria=[])
                for q in spec.questions
            ],
        )
        for i in range(5)
    ]
    human = {"A": {(g.student_id, q.question_id): 1.0 for g in grades for q in g.questions}}
    meta = {g.student_id: {"split": "test"} for g in grades}
    report = compare(spec, grades, human, meta)
    group = report["per_group"]["split"]["test"]
    assert report["vs_consensus"]["ci_method"] == group["ci_method"] == "cluster:question"
    system = [q.marks_awarded for g in grades for q in g.questions]
    groups = [q.question_id for g in grades for q in g.questions]
    expected = bootstrap_ci(system, [1.0] * 15, mean_absolute_error, groups=groups)
    assert report["vs_consensus"]["ci95"]["mae"] == group["ci95"]["mae"] == expected
    no_ci = compare(spec, grades, human, meta, ci=False)
    assert "ci95" not in no_ci["vs_consensus"]
    assert "ci95" not in no_ci["per_group"]["split"]["test"]
