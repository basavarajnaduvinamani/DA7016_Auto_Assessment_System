import pytest

from autoassess.budget import BudgetExceeded, openrouter_ledger
from autoassess.cache import DiskCache
from autoassess.config import GEMINI_BASE_URL, OPENROUTER_BASE_URL, Settings
from autoassess.providers import make_llm
from autoassess.providers.llm import OpenAICompatibleLLM


def _reply(cost):
    return {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 900, "completion_tokens": 80, "cost": cost}}


def test_openrouter_cost_is_recorded_and_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(OpenAICompatibleLLM, "_post", lambda self, p: _reply(0.004))
    ledger = openrouter_ledger(tmp_path, budget_usd=0.01)
    llm = OpenAICompatibleLLM(OPENROUTER_BASE_URL, "google/gemini-2.5-flash", "k", DiskCache(tmp_path, "llm"), ledger=ledger)
    llm.complete_json("s", "u1")
    llm.complete_json("s", "u1")  # cached: free and not counted
    llm.complete_json("s", "u2")
    llm.complete_json("s", "u3")
    assert ledger.calls() == 3 and ledger.spent() == pytest.approx(0.012)
    with pytest.raises(BudgetExceeded, match="OPENROUTER_BUDGET_USD"):
        llm.complete_json("s", "u4")
    llm.complete_json("s", "u2")  # cached answers still work after the cap
    assert "$0.01 of $0.01 (3 paid calls)" in ledger.summary()


def test_only_openrouter_gets_a_ledger(tmp_path):
    common = dict(cache_dir=tmp_path, llm_model="m", llm_api_key="k", openrouter_api_key="")
    assert make_llm(Settings(llm_provider="openrouter", llm_base_url=OPENROUTER_BASE_URL, **common)).ledger is not None
    assert make_llm(Settings(llm_provider="gemini", llm_base_url=GEMINI_BASE_URL, **common)).ledger is None
    assert make_llm(Settings(llm_provider="custom", llm_base_url="http://localhost:11434/v1", **common)).ledger is None


def test_budget_defaults_match_course_credits(monkeypatch):
    monkeypatch.delenv("BODHAN_BUDGET_INR", raising=False)
    monkeypatch.delenv("OPENROUTER_BUDGET_USD", raising=False)
    s = Settings()
    assert s.bodhan_budget_inr < 110 and s.openrouter_budget_usd < 20
