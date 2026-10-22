"""Confidence: when to trust a mark and when to ask a human.

Each signal is a number in [0, 1] where 1 means no sign of trouble:
- run_agreement: 1 - (spread of marks across the grader's runs) / max marks
- model_agreement: 1 - |first examiner - second examiner| / max marks; a
  different model disagreeing is a better warning than one model's runs
  disagreeing with each other, which mostly measures sampling noise
- review_agreement: 1 - (marks the critic took away + marks the advocate
  added) / max marks
- ocr: mean OCR line confidence
- evidence: 1 - share of criteria whose quote had to be withdrawn

A question's confidence is the lowest signal, so any one warning is enough to
send it for review. Below the threshold it is marked "?" on the sheet.
`coverage_curve` reports what that buys: accuracy on the questions accepted
automatically at each threshold, against the share accepted.
"""

from __future__ import annotations

from collections.abc import Sequence


def combine_signals(signals: dict[str, float]) -> float:
    if not signals:
        return 1.0
    return round(max(0.0, min(1.0, min(signals.values()))), 3)


def coverage_curve(
    confidence: Sequence[float],
    system: Sequence[float],
    human: Sequence[float],
    max_marks: Sequence[float],
    thresholds: Sequence[float] = (0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95),
    tolerance: float = 0.5,
) -> list[dict]:
    """For each threshold: share auto-accepted, and on that share the MAE, signed bias and share within tolerance."""
    rows = []
    n = len(confidence)
    for t in thresholds:
        keep = [i for i in range(n) if confidence[i] >= t]
        if not keep:
            rows.append({"threshold": t, "coverage": 0.0, "n": 0})
            continue
        err = [system[i] - human[i] for i in keep]
        rows.append(
            {
                "threshold": t,
                "coverage": round(len(keep) / n, 3),
                "n": len(keep),
                "mae": round(sum(abs(e) for e in err) / len(err), 3),
                "bias": round(sum(err) / len(err), 3),
                "nmae": round(sum(abs(err[j]) / max_marks[i] for j, i in enumerate(keep)) / len(keep), 3),
                "within_tolerance": round(sum(abs(e) <= tolerance + 1e-9 for e in err) / len(err), 3),
            }
        )
    return rows
