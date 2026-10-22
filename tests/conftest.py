from pathlib import Path

import pytest

from autoassess.providers.base import LLMClient

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_exam"


class FakeLLM(LLMClient):
    """Returns queued replies in order and records the prompts it saw."""

    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, system, user, *, temperature=0.0, seed=None):
        self.calls.append((system, user))
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """Real keys in the environment must never turn a test into a paid live call."""
    for var in (
        "AUTOASSESS_LLM_PROVIDER", "AUTOASSESS_LLM_API_KEY", "AUTOASSESS_LLM_BASE_URL", "AUTOASSESS_LLM_MODEL",
        "GEMINI_API_KEY", "OPENROUTER_API_KEY", "BODHAN_API_KEY", "BODHAN_OCR_API_KEY", "BODHAN_TRANSLATE_API_KEY",
    ):  # fmt: skip
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sample_spec_path():
    return SAMPLE / "exam_spec.yaml"
