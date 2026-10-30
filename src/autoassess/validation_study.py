"""Offline, paired evaluation of anonymised question-level score records.

All model and threshold choices belong to development data. These utilities
never call providers or turn missing predictions into estimated results.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from autoassess.metrics import mean_absolute_error, quadratic_weighted_kappa, signed_bias, within


@dataclass(frozen=True)
class Score:
    """A text-free score pair; identifiers must be anonymised before export."""

    item_id: str
    question_id: str
    split: str
    system: float
    human: float
    max_marks: float
    confidence: float
    needs_review: bool
    human_a: float
    human_b: float

    def __post_init__(self) -> None:
        if not self.item_id or not self.question_id or self.split not in {"dev", "test"}:
            raise ValueError("nonempty identifiers and dev/test split required")
        numbers = (self.system, self.human, self.max_marks, self.confidence, self.human_a, self.human_b)
        if not all(math.isfinite(x) for x in numbers) or self.max_marks <= 0:
            raise ValueError("finite scores and positive maximum required")
        if not all(0 <= x <= self.max_marks for x in (self.system, self.human, self.human_a, self.human_b)):
            raise ValueError("scores outside question bounds")
        if not 0 <= self.confidence <= 1 or not isinstance(self.needs_review, bool):
            raise ValueError("invalid confidence or review decision")
        if not math.isclose(self.human, (self.human_a + self.human_b) / 2, abs_tol=1e-12):
            raise ValueError("consensus must be the mean of the two human marks")


def validate_split(rows: Sequence[Score]) -> None:
    """Reject duplicate observations and question leakage across dev and test."""
    if not rows or len({r.item_id for r in rows}) != len(rows):
        raise ValueError("nonempty unique items required")
    splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        splits[row.question_id].add(row.split)
    if any(len(values) != 1 for values in splits.values()):
        raise ValueError("question leakage across dev and test")


def score_metrics(rows: Sequence[Score]) -> dict:
    """Compute full precision metrics using the project's half-mark QWK bins."""
    if not rows:
        raise ValueError("cannot evaluate empty scores")
    system, human = [r.system for r in rows], [r.human for r in rows]
    return {
        "n": len(rows),
        "questions": len({r.question_id for r in rows}),
        "qwk": quadratic_weighted_kappa(system, human),
        "mae": mean_absolute_error(system, human),
        "bias": signed_bias(system, human),
        "within_1": within(system, human),
        "exact": within(system, human, 0),
    }


def fit_referral(dev: Sequence[Score], minimum_coverage: float = 0.5) -> dict:
    """Minimise development accepted MAE subject to a fixed coverage floor.

    Ties prefer higher coverage, then the lower threshold. Explicit review
    decisions always veto acceptance, even at a low confidence threshold.
    """
    if not dev or any(r.split != "dev" for r in dev) or not 0 < minimum_coverage <= 1:
        raise ValueError("development rows and a valid coverage floor required")
    validate_split(dev)
    candidates = []
    for threshold in sorted({0.0, *(r.confidence for r in dev)}):
        accepted = [r for r in dev if r.confidence >= threshold and not r.needs_review]
        coverage = len(accepted) / len(dev)
        if accepted and coverage >= minimum_coverage:
            candidates.append((score_metrics(accepted)["mae"], -coverage, threshold))
    if not candidates:
        raise ValueError("no threshold achieves the development coverage floor with review vetoes")
    risk, negative_coverage, threshold = min(candidates)
    return {
        "threshold": threshold,
        "dev_mae": risk,
        "dev_coverage": -negative_coverage,
        "minimum_coverage": minimum_coverage,
        "objective": "minimise accepted MAE; review vetoes acceptance",
    }


def risk_coverage(test: Sequence[Score], frozen: dict, *, seed: int = 0, draws: int = 1000) -> dict:
    """Evaluate a frozen development threshold and a descriptive test curve.

    Random referral samples the same number of test answers uniformly; its
    percentile band measures random selection variation, not model uncertainty.
    Test curve points must never be used to refit the threshold.
    """
    if not test or any(r.split != "test" for r in test) or draws < 1:
        raise ValueError("test rows and positive draws required")
    validate_split(test)
    rng = random.Random(seed)
    points = []
    errors = [abs(r.system - r.human) for r in test]
    random_expected_mae = sum(errors) / len(errors)
    for threshold in sorted({0.0, frozen["threshold"], *(r.confidence for r in test)}):
        accepted = [r for r in test if r.confidence >= threshold and not r.needs_review]
        k = len(accepted)
        samples = sorted(sum(rng.sample(errors, k)) / k for _ in range(draws)) if k else []
        points.append(
            {
                "threshold": threshold,
                "accepted": k,
                "coverage": k / len(test),
                "accepted_mae": score_metrics(accepted)["mae"] if k else None,
                "random_expected_mae": random_expected_mae if k else None,
                "random_selection_mae_p025_p975": [samples[int(p * (draws - 1))] for p in (0.025, 0.975)]
                if k
                else None,
            }
        )
    return {
        "seed": seed,
        "draws": draws,
        "frozen_dev": frozen,
        "curve": points,
        "selected": next(p for p in points if p["threshold"] == frozen["threshold"]),
    }


def paired_comparison(default: Sequence[Score], baseline: Sequence[Score], *, seed: int = 0, draws: int = 2000) -> dict:
    """Return default-minus-baseline differences with paired question bootstrap.

    The identical sampled question clusters, including every answer in each
    cluster, are used for both systems in each replicate. No inner join hides
    missing predictions. Percentiles use floor indices, without rounding.
    """
    validate_split(default)
    validate_split(baseline)
    other = {r.item_id: r for r in baseline}
    if len(default) != len(baseline) or set(other) != {r.item_id for r in default} or draws < 1:
        raise ValueError("complete matched predictions and positive draws required")
    paired = [other[r.item_id] for r in default]
    for a, b in zip(default, paired, strict=True):
        if (a.question_id, a.split, a.human, a.max_marks, a.human_a, a.human_b) != (
            b.question_id,
            b.split,
            b.human,
            b.max_marks,
            b.human_a,
            b.human_b,
        ):
            raise ValueError("mismatched reference scores, questions or split")
    if len({r.split for r in default}) != 1:
        raise ValueError("compare one split at a time")
    clusters: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(default):
        clusters[row.question_id].append(i)
    if len(clusters) < 2:
        raise ValueError("at least two question clusters required")
    groups = list(clusters.values())
    rng = random.Random(seed)
    diffs: dict[str, list[float]] = {"qwk": [], "mae": []}
    for _ in range(draws):
        indices = [i for _ in groups for i in rng.choice(groups)]
        a, b = score_metrics([default[i] for i in indices]), score_metrics([paired[i] for i in indices])
        for metric in diffs:
            diffs[metric].append(a[metric] - b[metric])
    a, b = score_metrics(default), score_metrics(paired)
    return {
        "default": a,
        "baseline": b,
        "seed": seed,
        "draws": draws,
        "method": "paired question-cluster percentile bootstrap; default minus baseline",
        "differences": {
            m: {"estimate": a[m] - b[m], "ci95": [sorted(values)[int(p * (draws - 1))] for p in (0.025, 0.975)]}
            for m, values in diffs.items()
        },
    }
