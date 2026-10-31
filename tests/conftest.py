import os
import uuid
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
def _no_real_keys(monkeypatch, tmp_path):
    """Real keys in the environment must never turn a test into a paid live call,
    and fake paid calls must never land in the real spend ledgers under ./.cache."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOASSESS_CACHE_DIR", str(tmp_path / ".cache"))
    for var in (
        "AUTOASSESS_LLM_PROVIDER", "AUTOASSESS_LLM_API_KEY", "AUTOASSESS_LLM_BASE_URL", "AUTOASSESS_LLM_MODEL",
        "GEMINI_API_KEY", "OPENROUTER_API_KEY", "BODHAN_API_KEY", "BODHAN_OCR_API_KEY", "BODHAN_TRANSLATE_API_KEY",
        "DATABASE_URL", "AUTOASSESS_S3_BUCKET", "RESEND_API_KEY", "BREVO_API_KEY", "AUTOASSESS_MAIL_BACKEND",
        "AUTOASSESS_MAIL_FROM", "AUTOASSESS_PILOT_EMAILS", "AUTOASSESS_ADMIN_EMAILS",
    ):  # fmt: skip
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _postgres_when_asked(request, monkeypatch):
    """With AUTOASSESS_TEST_DATABASE_URL set, every web test runs on its own fresh Postgres database.

    Use an IP, not localhost (the web tests block DNS lookups): AUTOASSESS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres pytest tests/test_web_*.py
    """
    admin_url = os.getenv("AUTOASSESS_TEST_DATABASE_URL", "")
    if not admin_url or not Path(str(request.node.fspath)).name.startswith("test_web"):
        yield
        return
    import psycopg

    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    monkeypatch.setenv("DATABASE_URL", admin_url.rsplit("/", 1)[0] + "/" + name)
    yield
    from autoassess.web.db import close_all

    close_all()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture
def sample_spec_path():
    return SAMPLE / "exam_spec.yaml"
