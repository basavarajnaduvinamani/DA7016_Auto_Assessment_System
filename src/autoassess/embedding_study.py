"""Fit a cosine-embedding baseline using development marks only.

Frozen sentence embeddings are supplied by the caller. Model identity, revision,
input hashes and the encoding command belong in its evidence manifest; these
functions do not download weights, call providers or grade rubric criteria.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def cosine(answer: Sequence[float], reference: Sequence[float]) -> float:
    """Return bounded cosine similarity, with zero for an empty/zero vector."""
    if not answer or len(answer) != len(reference) or not all(math.isfinite(x) for x in (*answer, *reference)):
        raise ValueError("equal nonempty finite embedding vectors required")
    den = math.sqrt(sum(x * x for x in answer) * sum(x * x for x in reference))
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(answer, reference, strict=True)) / den)) if den else 0.0


def fit_similarity(dev_similarities: Sequence[float], dev_fractions: Sequence[float]) -> dict:
    """Fit an intercept and nonnegative least-squares slope on dev scores.

    Labels are human marks divided by question maximum. The caller must pass
    development examples only. A constant similarity yields the dev mean.
    """
    if not dev_similarities or len(dev_similarities) != len(dev_fractions):
        raise ValueError("equal nonempty development similarities and labels required")
    if not all(math.isfinite(x) and -1 <= x <= 1 for x in dev_similarities):
        raise ValueError("invalid development cosine")
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in dev_fractions):
        raise ValueError("invalid development score fraction")
    xmean, ymean = sum(dev_similarities) / len(dev_similarities), sum(dev_fractions) / len(dev_fractions)
    variance = sum((x - xmean) ** 2 for x in dev_similarities)
    covariance = sum((x - xmean) * (y - ymean) for x, y in zip(dev_similarities, dev_fractions, strict=True))
    slope = max(0.0, covariance / variance) if variance else 0.0
    return {"slope": slope, "intercept": ymean - slope * xmean, "training_split": "dev"}


def similarity_mark(similarity: float, max_marks: float, frozen: dict, *, blank: bool = False) -> float:
    """Map cosine to a bounded mark with a frozen dev fit; blank answers earn zero."""
    if not math.isfinite(similarity) or not -1 <= similarity <= 1 or not math.isfinite(max_marks) or max_marks <= 0:
        raise ValueError("finite cosine and positive maximum required")
    if frozen.get("training_split") != "dev":
        raise ValueError("development fit required")
    return 0.0 if blank else max(0.0, min(max_marks, max_marks * (frozen["intercept"] + frozen["slope"] * similarity)))
