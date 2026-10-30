"""Agreement metrics between system marks and human marks."""

from __future__ import annotations

import math
from collections.abc import Sequence


def quadratic_weighted_kappa(a: Sequence[float], b: Sequence[float], step: float = 0.5) -> float:
    """QWK between two raters. Marks are binned to `step` (default half marks)."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty mark lists")
    ia = [round(x / step) for x in a]
    ib = [round(x / step) for x in b]
    lo, hi = min(ia + ib), max(ia + ib)
    n = hi - lo + 1
    if n == 1:
        return 1.0
    obs = [[0.0] * n for _ in range(n)]
    for x, y in zip(ia, ib, strict=False):
        obs[x - lo][y - lo] += 1
    hist_a = [sum(row) for row in obs]
    hist_b = [sum(obs[i][j] for i in range(n)) for j in range(n)]
    total = len(ia)
    num = den = 0.0
    for i in range(n):
        for j in range(n):
            w = (i - j) ** 2 / (n - 1) ** 2
            num += w * obs[i][j]
            den += w * hist_a[i] * hist_b[j] / total
    return 1.0 - num / den if den else 1.0


def mean_absolute_error(a: Sequence[float], b: Sequence[float]) -> float:
    """Return the mean absolute difference between paired marks."""
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def within(a: Sequence[float], b: Sequence[float], tolerance: float = 1.0) -> float:
    """Share of items where the two marks differ by at most `tolerance`."""
    return sum(abs(x - y) <= tolerance + 1e-9 for x, y in zip(a, b, strict=True)) / len(a)


def signed_bias(system: Sequence[float], human: Sequence[float]) -> float:
    """Mean of system - human: negative means the system under-marks."""
    return sum(s - h for s, h in zip(system, human, strict=True)) / len(system)


def bootstrap_ci(
    system: Sequence[float],
    human: Sequence[float],
    metric,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
    groups: Sequence[str] | None = None,
) -> tuple[float, float]:
    """Percentile interval, resampling items or whole groups with replacement."""
    import random

    rng = random.Random(seed)
    n = len(system)
    if len(human) != n or (groups is not None and len(groups) != n):
        raise ValueError("marks and groups must have equal lengths")
    clusters: dict[str, list[int]] = {}
    if groups is not None:
        for i, group in enumerate(groups):
            clusters.setdefault(group, []).append(i)
    members = list(clusters.values())
    stats = []
    for _ in range(n_boot):
        if groups is None:
            idx = [rng.randrange(n) for _ in range(n)]
        else:
            idx = [i for _ in members for i in members[rng.randrange(len(members))]]
        try:
            v = metric([system[i] for i in idx], [human[i] for i in idx])
        except (ValueError, ZeroDivisionError):
            continue
        if v == v:  # skip NaN
            stats.append(v)
    if not stats:
        return float("nan"), float("nan")
    stats.sort()
    lo = stats[int(alpha / 2 * (len(stats) - 1))]
    hi = stats[int((1 - alpha / 2) * (len(stats) - 1))]
    return round(lo, 3), round(hi, 3)


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Return Pearson correlation, or NaN when a sequence has no variation."""
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va and vb else float("nan")


def agreement_report(
    system: Sequence[float],
    human: Sequence[float],
    max_marks: Sequence[float] | None = None,
    ci: bool = False,
    groups: Sequence[str] | None = None,
) -> dict:
    """Summarise paired marks, optionally adding bootstrap confidence intervals."""
    report = {
        "n": len(system),
        "ci_method": "cluster:question" if groups is not None else "item",
        "qwk": round(quadratic_weighted_kappa(system, human), 3),
        "mae": round(mean_absolute_error(system, human), 3),
        "within_1": round(within(system, human, 1.0), 3),
        "exact": round(within(system, human, 0.0), 3),
        "pearson": round(pearson(system, human), 3),
        "mean_system": round(sum(system) / len(system), 3),
        "mean_human": round(sum(human) / len(human), 3),
        "bias": round(signed_bias(system, human), 3),
    }
    if max_marks is not None:
        report["nmae"] = round(
            sum(abs(s - h) / m for s, h, m in zip(system, human, max_marks, strict=True)) / len(system), 3
        )
    if ci and len(system) >= 5:
        report["ci95"] = {
            "qwk": bootstrap_ci(system, human, quadratic_weighted_kappa, groups=groups),
            "mae": bootstrap_ci(system, human, mean_absolute_error, groups=groups),
            "bias": bootstrap_ci(system, human, signed_bias, groups=groups),
        }
    return report


def _edit_distance(a: Sequence, b: Sequence) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _ocr_norm(text: str) -> str:
    return " ".join(text.split())


def character_error_rate(hypothesis: str, reference: str) -> float:
    """Measure character edit distance relative to normalised reference length."""
    ref = _ocr_norm(reference)
    return _edit_distance(_ocr_norm(hypothesis), ref) / max(1, len(ref))


def word_error_rate(hypothesis: str, reference: str) -> float:
    """Measure word edit distance relative to reference word count."""
    ref = reference.split()
    return _edit_distance(hypothesis.split(), ref) / max(1, len(ref))
