import pytest

from autoassess.cache import DiskCache, content_key
from autoassess.config import Settings
from autoassess.providers import make_ocr
from autoassess.providers.llm import parse_json_reply
from conftest import SAMPLE


def test_cache_computes_once(tmp_path):
    cache = DiskCache(tmp_path, "t")
    calls = []
    key = content_key("x", {"b": 1, "a": 2})
    for _ in range(3):
        assert cache.get_or_compute(key, lambda: calls.append(1) or {"v": 1}) == {"v": 1}
    assert len(calls) == 1


def test_content_key_ignores_dict_order():
    assert content_key({"a": 1, "b": 2}) == content_key({"b": 2, "a": 1})


def test_parse_json_reply_handles_fences():
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_reply('Sure! {"a": [1, 2]} hope that helps') == {"a": [1, 2]}


def test_text_ocr_reads_sheet():
    page = make_ocr(Settings(ocr_provider="text")).read_page(SAMPLE / "answer_sheets" / "S002.txt", 0)
    assert page.lines[0].text.startswith("1. Attention")
    assert "Hallucination" in page.text


def test_bodhan_requires_key():
    with pytest.raises(ValueError, match="BODHAN_API_KEY"):
        make_ocr(Settings(ocr_provider="bodhan", bodhan_api_key=""))


def test_llm_rate_limit_backs_off_and_retries(monkeypatch):
    import io
    import urllib.error

    from autoassess.providers import llm as llm_mod

    tries = []

    def urlopen(req, timeout):
        tries.append(1)
        if len(tries) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"{}"))
        return io.BytesIO(b'{"ok": 1}')

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    client = llm_mod.OpenAICompatibleLLM("https://example.test/v1", "m")
    assert client._post({}) == {"ok": 1} and len(tries) == 3


def test_llm_retries_once_after_cached_malformed_reply(tmp_path, monkeypatch):
    import autoassess.providers.llm as llm_mod

    replies = iter(['{"a" 1}', '{"a": 2}'])
    client = llm_mod.OpenAICompatibleLLM("https://example.test/v1", "m", cache=DiskCache(tmp_path, "llm"))
    monkeypatch.setattr(client, "_post", lambda payload: {"choices": [{"message": {"content": next(replies)}}]})
    assert client.complete_json("s", "u") == {"a": 2}
    # Both replies are now cached, so a rerun makes no new call.
    assert client.complete_json("s", "u") == {"a": 2}
