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
    for x, y in zip(ia, ib):
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
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def within(a: Sequence[float], b: Sequence[float], tolerance: float = 1.0) -> float:
    """Share of items where the two marks differ by at most `tolerance`."""
    return sum(abs(x - y) <= tolerance + 1e-9 for x, y in zip(a, b, strict=True)) / len(a)


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va and vb else float("nan")


def agreement_report(system: Sequence[float], human: Sequence[float], max_marks: Sequence[float] | None = None) -> dict:
    report = {
        "n": len(system),
        "qwk": round(quadratic_weighted_kappa(system, human), 3),
        "mae": round(mean_absolute_error(system, human), 3),
        "within_1": round(within(system, human, 1.0), 3),
        "exact": round(within(system, human, 0.0), 3),
        "pearson": round(pearson(system, human), 3),
        "mean_system": round(sum(system) / len(system), 3),
        "mean_human": round(sum(human) / len(human), 3),
    }
    if max_marks is not None:
        report["nmae"] = round(sum(abs(s - h) / m for s, h, m in zip(system, human, max_marks, strict=True)) / len(system), 3)
    return report
