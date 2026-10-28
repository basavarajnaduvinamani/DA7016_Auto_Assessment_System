import pytest
from conftest import SAMPLE

from autoassess.baseline import grade_sheet_lexical
from autoassess.metrics import agreement_report, quadratic_weighted_kappa, within
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.segment import segment_pages
from autoassess.spec_builder import load_spec


def test_qwk_perfect_and_reversed():
    assert quadratic_weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == pytest.approx(1.0)
    assert quadratic_weighted_kappa([0, 1, 2, 3], [3, 2, 1, 0]) < 0


def test_qwk_matches_sklearn_formula():
    # Reference value computed with sklearn.metrics.cohen_kappa_score(weights="quadratic").
    a = [0, 1, 1, 2, 3, 3, 2, 0]
    b = [0, 1, 2, 2, 3, 2, 2, 1]
    assert quadratic_weighted_kappa(a, b, step=1) == pytest.approx(0.8125, abs=1e-4)


def test_within_and_report():
    assert within([1, 2, 5], [1.5, 4, 5], 1) == pytest.approx(2 / 3)
    r = agreement_report([1, 2, 3], [1, 2, 4], [5, 5, 5])
    assert r["exact"] == pytest.approx(0.667, abs=1e-3) and r["nmae"] == pytest.approx(0.067, abs=1e-3)


def test_lexical_baseline_ranks_sample_sheets():
    spec = load_spec(SAMPLE / "exam_spec.yaml")
    totals = {}
    for sid in ("S001", "S002", "S003"):
        pages = [PlainTextOCR().read_page(SAMPLE / "answer_sheets" / f"{sid}.txt", 0)]
        totals[sid] = grade_sheet_lexical(spec, segment_pages(spec, pages), sid).total
    assert totals["S001"] > totals["S002"] > totals["S003"]
