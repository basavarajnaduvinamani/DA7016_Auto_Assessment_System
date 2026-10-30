"""Review choices route independently in single-sheet and class demo grading."""

import socket

import pytest
from conftest import SAMPLE

from autoassess import demo
from autoassess.classwork import grade_class
from autoassess.config import Settings
from autoassess.providers.scripted import ScriptedLLM
from autoassess.spec_builder import load_spec


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("advocate,critic", [(True, False), (False, False), (False, True), (True, True)])
def test_independent_review_options(monkeypatch, tmp_path, batch, advocate, critic):
    def blocked(*args, **kwargs):
        pytest.fail("Demo defaults tests must not call the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.delenv("AUTOASSESS_DEMO_DRY_RUN", raising=False)
    reviewer = ScriptedLLM()
    monkeypatch.setattr(demo, "make_llm", lambda settings, **kwargs: reviewer)
    calls = []

    def record(*args, **kwargs):
        calls.append(kwargs)
        return (grade_class if batch else original_run)(*args, **kwargs)

    original_run = demo.run
    if batch:
        monkeypatch.setattr("autoassess.classwork.grade_class", record)
    else:
        monkeypatch.setattr(demo, "run", record)
    settings = Settings(cache_dir=tmp_path, llm_provider="fake")
    spec = load_spec(SAMPLE / "exam_spec.yaml")
    opts = demo.Options(advocate_review=advocate, strict_critic=critic, runs=1, annotate=False)
    sheet = SAMPLE / "answer_sheets/S002.txt"
    if batch:
        demo.mark_class(spec, [sheet], opts, settings)
    else:
        demo.mark_sheet(spec, sheet, opts, settings)
    assert len(calls) == 1  # no provider failure hidden by baseline fallback
    assert calls[0]["advocate"] is (reviewer if advocate else None)
    assert calls[0]["critic"] is (reviewer if critic else None)


def test_options_default_to_advocate_only():
    assert demo.Options().advocate_review is True
    assert demo.Options().strict_critic is False
