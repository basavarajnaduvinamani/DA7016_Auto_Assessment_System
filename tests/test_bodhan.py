import json

import pytest

from autoassess.cache import DiskCache
from autoassess.providers.bodhan import BodhanOCR, BodhanTranslate, BudgetExceeded, language_code


def _fake_ocr_response():
    return {
        "choices": [{"message": {"content": "Ans 1. Queries keys and values"}}],
        "blocks": [
            {
                "order": 0,
                "label": "paragraph",
                "type": "Text",
                "bbox_xyxy": [10, 20, 300, 60],
                "conf": 0.93,
                "text": "Ans 1. Queries keys and values",
            }
        ],
    }


def test_ocr_request_shape_cache_and_ledger(tmp_path):
    img = tmp_path / "page_000.png"
    img.write_bytes(b"\x89PNG fake")
    ocr = BodhanOCR("k", "https://api.bodhan.ai/v1", DiskCache(tmp_path / "c", "ocr"), budget_inr=10)
    sent = []
    ocr.client._post = lambda path, body: sent.append((path, body)) or _fake_ocr_response()
    p1 = ocr.read_page(img, 0)
    p2 = ocr.read_page(img, 0)
    assert len(sent) == 1  # second read is cached
    path, body = sent[0]
    assert ocr.client.base_url == "https://api.bodhan.ai" and path == "/v1/chat/completions"
    assert body["model"] == "indic-ocr"
    assert body["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert p1.lines[0].bbox.x1 == 300 and p1.lines[0].confidence == 0.93 and p2.text == p1.text
    assert json.loads((tmp_path / "c" / "bodhan_ledger.json").read_text())["spent_inr"] == 0.2


def test_ocr_markdown_fallback_without_blocks(tmp_path):
    img = tmp_path / "p.png"
    img.write_bytes(b"x")
    ocr = BodhanOCR("k", cache=None)
    ocr.client._post = lambda path, body: {"choices": [{"message": {"content": "line one\nline two"}}]}
    assert [line.text for line in ocr.read_page(img, 0).lines] == ["line one", "line two"]


def test_budget_stops_paid_calls(tmp_path):
    img = tmp_path / "p.png"
    ocr = BodhanOCR("k", cache=DiskCache(tmp_path / "c", "ocr"), budget_inr=0.3)
    ocr.client._post = lambda path, body: _fake_ocr_response()
    img.write_bytes(b"a")
    ocr.read_page(img, 0)
    img.write_bytes(b"b")
    with pytest.raises(BudgetExceeded):
        ocr.read_page(img, 0)


def test_translate_per_paragraph_with_codes(tmp_path):
    tr = BodhanTranslate("k", cache=DiskCache(tmp_path / "c", "tr"), budget_inr=5)
    sent = []

    def post(path, body):
        sent.append((path, body))
        text = body["messages"][0]["content"]
        reply = {"content": f"<{body['target_language']}>{text}"}
        return {"choices": [{"message": reply, "finish_reason": "stop"}], "usage": {"completion_tokens": 20}}

    tr.client._post = post
    out = tr.translate("First line.\n\nSecond line.", "Kannada")
    assert out == "<kn>First line.\n\n<kn>Second line."
    assert [b["messages"][0]["content"] for _, b in sent] == ["First line.", "Second line."]
    assert sent[0][0] == "/v1/chat/completions" and sent[0][1]["model"] == "indic-translate"
    tr.translate("First line.", "kn")
    assert len(sent) == 2  # cached
    assert tr.translate("Same", "English") == "Same"


def test_language_codes():
    assert language_code("Hindi") == "hi" and language_code("kn") == "kn" and language_code("sd-Arab") == "sd-Arab"
    with pytest.raises(ValueError):
        language_code("Klingon")


def test_truncated_page_is_read_in_halves(tmp_path):
    from PIL import Image

    from autoassess.providers.bodhan import BodhanError

    img = tmp_path / "page_000.png"
    Image.new("RGB", (100, 200), "white").save(img)
    ocr = BodhanOCR("k", "https://api.bodhan.ai/v1", None, budget_inr=10)
    calls = []

    def post(path, body):
        calls.append(body)
        if len(calls) == 1:
            raise BodhanError("502: 1 of 3 blocks (order 2: truncated); the page was not transcribed")
        return _fake_ocr_response()

    ocr.client._post = post
    page = ocr.read_page(img, 0)
    assert len(calls) == 3 and len(page.lines) == 2
    assert page.lines[1].bbox.y0 == 20 + 100  # bottom half shifted down by half the page


def test_rate_limit_backs_off_and_retries(tmp_path, monkeypatch):
    import io
    import urllib.error

    from autoassess.providers import bodhan

    tries = []

    def urlopen(req, timeout):
        tries.append(1)
        if len(tries) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"{}"))
        return io.BytesIO(b'{"ok": 1}')

    monkeypatch.setattr(bodhan.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(bodhan.time, "sleep", lambda s: None)
    ocr = BodhanOCR("k", "https://api.bodhan.ai/v1", None, budget_inr=10)
    assert ocr.client._post("/v1/x", {}) == {"ok": 1} and len(tries) == 3
