"""Check cosine calibration independently of any embedding library or weights."""

import pytest

from autoassess.embedding_study import cosine, fit_similarity, similarity_mark


def test_cosine_and_zero_vectors():
    assert cosine([1, 0], [1, 0]) == 1
    assert cosine([1, 0], [0, 1]) == 0
    assert cosine([0, 0], [1, 0]) == 0
    assert cosine([-1, 0], [1, 0]) == -1
    for a, b in [([], []), ([1], [1, 2]), ([float("nan")], [1])]:
        with pytest.raises(ValueError):
            cosine(a, b)


def test_dev_fit_mapping_bounds_and_blanks():
    frozen = fit_similarity([0, 0.5, 1], [0, 0.5, 1])
    assert frozen == {"slope": 1, "intercept": 0, "training_split": "dev"}
    assert similarity_mark(0.5, 5, frozen) == 2.5
    assert similarity_mark(-1, 5, frozen) == 0
    assert similarity_mark(1, 5, frozen, blank=True) == 0
    constant = fit_similarity([1, 1], [0.2, 0.6])
    assert similarity_mark(0.5, 5, constant) == 2
    assert fit_similarity([0, 1], [1, 0])["slope"] == 0
    with pytest.raises(ValueError):
        fit_similarity([1], [])
    with pytest.raises(ValueError, match="development"):
        similarity_mark(0.5, 5, {"training_split": "test"})
