"""Verify development-only fitting, paired resampling and strict score exports."""

from dataclasses import replace

import pytest

from autoassess.validation_study import Score, fit_referral, paired_comparison, risk_coverage, validate_split


def _scores(split="dev"):
    return [
        Score(str(i), str(i // 2), split, s, h, 5, c, False, h, h, False)
        for i, (s, h, c) in enumerate([(0, 0, 0.9), (1, 1, 0.9), (0, 4, 0.2), (0, 5, 0.2)])
    ]


def test_threshold_fits_dev_and_is_frozen_when_test_marks_change():
    dev = _scores()
    frozen = fit_referral(dev)
    assert frozen["threshold"] == 0.9
    assert frozen["dev_coverage"] == 0.5
    test = [replace(r, split="test", question_id="test" + r.question_id) for r in dev]
    result = risk_coverage(test, frozen, draws=30)
    assert result["selected"]["coverage"] == 0.5
    assert result["selected"]["accepted_mae"] == 0
    assert result["selected"]["random_expected_mae"] == 2.25
    changed = [replace(r, system=5) for r in test]
    assert risk_coverage(changed, frozen, draws=30)["frozen_dev"] == frozen
    assert risk_coverage(test, frozen, draws=30) == result
    with pytest.raises(ValueError, match="development"):
        fit_referral(test)


def test_referral_veto_and_unattainable_coverage():
    rows = [replace(r, needs_review=True, forced_review=True) for r in _scores()]
    with pytest.raises(ValueError, match="coverage"):
        fit_referral(rows)
    result = risk_coverage([replace(r, split="test") for r in rows], {"threshold": 0.8}, draws=2)
    assert result["selected"]["accepted"] == 0
    assert result["selected"]["accepted_mae"] is None


def test_calibration_can_replace_old_confidence_threshold_but_needs_flag_metadata():
    rows = [replace(r, needs_review=r.confidence < 0.8) for r in _scores()]
    assert fit_referral(rows, minimum_coverage=1)["dev_coverage"] == 1
    with pytest.raises(ValueError, match="metadata"):
        fit_referral([replace(r, forced_review=None) for r in rows])


def test_duplicate_and_leaked_questions_are_rejected():
    rows = _scores()
    with pytest.raises(ValueError, match="unique"):
        validate_split([*rows, rows[0]])
    with pytest.raises(ValueError, match="leakage"):
        validate_split([rows[0], replace(rows[1], split="test")])


def test_paired_resampling_identity_reorder_and_missing_predictions():
    rows = _scores("test")
    result = paired_comparison(rows, list(reversed(rows)), draws=100)
    assert result["differences"] == {m: {"estimate": 0, "ci95": [0, 0]} for m in ("qwk", "mae")}
    with pytest.raises(ValueError, match="complete matched"):
        paired_comparison(rows, rows[:-1])
    with pytest.raises(ValueError, match="mismatched"):
        paired_comparison(rows, [replace(r, human=0, human_a=0, human_b=0) for r in rows])


def test_question_clusters_and_difference_direction():
    # Two question clusters, equal size: per-cluster default errors are 0 and 4.
    # A cluster bootstrap can only yield MAE differences 0, 2 or 4.
    base = [replace(r, item_id=f"{r.item_id}-{copy}", system=r.human) for copy in range(5) for r in _scores("test")]
    default = [replace(r, system=r.human + (4 if r.question_id == "0" else 0)) for r in base]
    result = paired_comparison(default, base, seed=7, draws=100)
    assert result["differences"]["mae"] == {"estimate": 2, "ci95": [0, 4]}
    assert result == paired_comparison(default, base, seed=7, draws=100)


@pytest.mark.parametrize(
    "change",
    [{"system": float("nan")}, {"system": -1}, {"max_marks": 0}, {"confidence": 1.1}, {"human": 3}, {"split": "train"}],
)
def test_invalid_scores_rejected(change):
    with pytest.raises(ValueError):
        replace(_scores()[0], **change)
