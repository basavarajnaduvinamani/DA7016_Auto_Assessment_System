import io
import json
import urllib.error

import pytest

from autoassess import doctor
from autoassess.cli import main
from autoassess.config import (
    GEMINI_BASE_URL,
    GEMINI_DEFAULT_MODEL,
    OPENROUTER_BASE_URL,
    OPENROUTER_DEFAULT_MODEL,
    Settings,
)
from autoassess.providers.bodhan import BodhanError, _BodhanClient
from autoassess.providers.llm import LLMError, OpenAICompatibleLLM

KEY_VARS = (
    "AUTOASSESS_LLM_PROVIDER", "AUTOASSESS_LLM_BASE_URL", "AUTOASSESS_LLM_MODEL", "AUTOASSESS_LLM_API_KEY",
    "GEMINI_API_KEY", "GEMINI_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
    "BODHAN_API_KEY", "BODHAN_OCR_API_KEY", "BODHAN_TRANSLATE_API_KEY",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """Real keys in the environment must never turn these tests into live calls."""
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def _settings(tmp_path, **kw):
    base = dict(
        cache_dir=tmp_path / "cache",
        llm_provider="gemini",
        openrouter_api_key="",
        llm_base_url=GEMINI_BASE_URL,
        llm_model=GEMINI_DEFAULT_MODEL,
        llm_api_key="AIzaFAKEKEY123456",
        bodhan_api_key="bodhan-fake-key-0001",
        bodhan_ocr_api_key="",
        bodhan_translate_api_key="",
    )
    return Settings(**{**base, **kw})


def _fake_bodhan(self, path, body):
    if path == "/translate":
        return {"translation": "अच्छा उत्तर।", "usage": {"output_tokens": 5}}
    return {
        "choices": [{"message": {"content": "Answer 1: a stack is LIFO"}}],
        "blocks": [
            {
                "order": 0,
                "type": "Text",
                "bbox_xyxy": [30, 50, 600, 100],
                "conf": 0.9,
                "text": "Answer 1: a stack is LIFO",
            }
        ],
    }


def test_provider_selection(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    s = Settings()  # only OpenRouter has a key
    assert (s.llm_provider, s.llm_base_url, s.llm_model, s.llm_api_key) == (
        "openrouter",
        OPENROUTER_BASE_URL,
        OPENROUTER_DEFAULT_MODEL,
        "or-key",
    )
    monkeypatch.setenv("AUTOASSESS_LLM_API_KEY", "g-key")
    s = Settings()  # both: free Gemini wins for development
    assert (s.llm_provider, s.llm_base_url, s.llm_model, s.llm_api_key) == (
        "gemini",
        GEMINI_BASE_URL,
        GEMINI_DEFAULT_MODEL,
        "g-key",
    )
    monkeypatch.setenv("AUTOASSESS_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-haiku")
    s = Settings()  # one line switches to OpenRouter for the demo
    assert (s.llm_provider, s.llm_model, s.llm_api_key) == ("openrouter", "anthropic/claude-haiku", "or-key")
    monkeypatch.setenv("AUTOASSESS_LLM_PROVIDER", "custom")
    monkeypatch.setenv("AUTOASSESS_LLM_BASE_URL", "http://localhost:11434/v1")
    s = Settings()
    assert (s.llm_base_url, s.llm_model) == ("http://localhost:11434/v1", "")  # no hosted model name forced on it
    monkeypatch.setenv("AUTOASSESS_LLM_PROVIDER", "claude")
    with pytest.raises(ValueError, match="AUTOASSESS_LLM_PROVIDER"):
        Settings()


def test_per_model_bodhan_keys_fall_back(tmp_path):
    s = _settings(tmp_path, bodhan_ocr_api_key="ocr-only")
    assert s.ocr_key == "ocr-only" and s.translate_key == "bodhan-fake-key-0001"


def test_all_checks_pass(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        OpenAICompatibleLLM,
        "_post",
        lambda self, payload: sent.append(payload) or {"choices": [{"message": {"content": '{"ok": true, "sum": 5}'}}]},
    )
    monkeypatch.setattr(_BodhanClient, "_post", _fake_bodhan)
    s = _settings(tmp_path)
    checks = doctor.run_doctor(s)
    assert [c.status for c in checks] == ["ok", "ok", "ok"], checks
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert "seed" not in sent[0]  # Gemini rejects it
    assert "1 line boxes" in checks[1].detail
    # Paid checks land in the ledger; nothing is cached, so a re-run tests the key again.
    assert json.loads((s.cache_dir / "bodhan_ledger.json").read_text())["spent_inr"] > 0.2
    assert not (s.cache_dir / "ocr").exists()
    text = doctor.report(s, checks)
    assert "AIza…3456" in text and "AIzaFAKEKEY123456" not in text


def test_failures_explain_next_step(tmp_path, monkeypatch):
    def bad_key(self, payload):
        raise LLMError("400 from gemini: API key not valid. Please pass a valid API key.", 400)

    def blocked(self, path, body):
        raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))

    monkeypatch.setattr(OpenAICompatibleLLM, "_post", bad_key)
    monkeypatch.setattr(_BodhanClient, "_post", blocked)
    checks = doctor.run_doctor(_settings(tmp_path))
    assert [c.status for c in checks] == ["FAIL", "FAIL", "FAIL"]
    assert "key was rejected" in checks[0].hint
    assert "allowed domains" in checks[1].hint and "api.bodhan.ai" in checks[1].hint


def test_explain_reads_bodhan_status():
    assert "no credit" in doctor.explain(BodhanError("402 insufficient_funds: top up (request_id=x)"), "api.bodhan.ai")
    assert "rate limited" in doctor.explain(LLMError("429 slow down", 429), "x")


def test_missing_keys_skip_and_free_mode(tmp_path):
    s = _settings(tmp_path, llm_api_key="", bodhan_api_key="")
    assert [c.status for c in doctor.run_doctor(s)] == ["skip", "skip", "skip"]
    assert [c.status for c in doctor.run_doctor(s, paid=False)][1:] == ["skip", "skip"]


def test_cli_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no .env here
    for var in (
        "AUTOASSESS_LLM_API_KEY",
        "GEMINI_API_KEY",
        "BODHAN_API_KEY",
        "BODHAN_OCR_API_KEY",
        "BODHAN_TRANSLATE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AUTOASSESS_LLM_API_KEY", "k-1234567890abcd")
    monkeypatch.setattr(OpenAICompatibleLLM, "_post", lambda self, p: (_ for _ in ()).throw(LLMError("401 nope", 401)))
    assert main(["doctor", "--free"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] LLM grader" in out and "skipped (--free)" in out


def test_seed_kept_for_other_endpoints_and_in_cache_key(tmp_path, monkeypatch):
    from autoassess.cache import DiskCache

    sent = []
    monkeypatch.setattr(
        OpenAICompatibleLLM, "_post", lambda self, p: sent.append(p) or {"choices": [{"message": {"content": "{}"}}]}
    )
    OpenAICompatibleLLM("http://localhost:11434/v1", "m").complete_json("s", "u", seed=3)
    assert sent[-1]["seed"] == 3
    gem = OpenAICompatibleLLM(GEMINI_BASE_URL, "m", "k", DiskCache(tmp_path, "llm"))
    for seed in (0, 1, 0):
        gem.complete_json("s", "u", temperature=0.3, seed=seed)
    assert len(sent) == 3  # seeds 0 and 1 are separate runs; the repeat of 0 is cached


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_openrouter_credit_and_standby_check(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fakefakefake")
    key_info = {"data": {"usage": 0.42, "limit": 20, "limit_remaining": 19.58, "limit_reset": None, "expires_at": None}}
    seen = []

    def urlopen(req, timeout=None):
        seen.append((req.full_url, req.headers.get("Authorization")))
        return _Resp(json.dumps(key_info).encode())

    monkeypatch.setattr(doctor.urllib.request, "urlopen", urlopen)
    llm_calls = []
    monkeypatch.setattr(
        OpenAICompatibleLLM,
        "_post",
        lambda self, p: (
            llm_calls.append((self.base_url, p["model"])) or {"choices": [{"message": {"content": '{"sum": 5}'}}]}
        ),
    )
    s = _settings(tmp_path, openrouter_api_key="sk-or-v1-fakefakefake")
    checks = {c.name: c for c in doctor.run_doctor(s, paid=False)}
    credit = checks["OpenRouter credit"]
    assert credit.status == "ok" and "$19.58 left" in credit.detail and "no expiry date" in credit.detail
    assert seen == [(f"{OPENROUTER_BASE_URL}/key", "Bearer sk-or-v1-fakefakefake")]
    assert checks[f"standby LLM [openrouter] ({OPENROUTER_DEFAULT_MODEL})"].status == "ok"
    assert (OPENROUTER_BASE_URL, OPENROUTER_DEFAULT_MODEL) in llm_calls and (
        GEMINI_BASE_URL,
        GEMINI_DEFAULT_MODEL,
    ) in llm_calls

    key_info["data"].update(limit_remaining=0.0, usage=20.0, expires_at="2027-06-30T00:00:00Z")
    credit = doctor.check_openrouter_credit(s)
    assert credit.status == "FAIL" and "expires 2027-06-30" in credit.detail and "used up" in credit.hint
