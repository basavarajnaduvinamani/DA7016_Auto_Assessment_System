"""`autoassess doctor`: check each configured key with one tiny live request.

Prints what is configured (keys masked), then one line per service: the active
LLM grader, any other hosted LLM that has a key (so switching providers is known
to work), the OpenRouter key's credit and expiry, Bodhan IndicOCR and Bodhan
Indic-Translate. Calls bypass the cache so
a cached answer can never hide a dead key. The two Bodhan checks cost about
Rs 0.20 together and are recorded in the budget ledger; --free skips them.
"""

from __future__ import annotations

import dataclasses
import json
import re
import socket
import struct
import tempfile
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path

from autoassess.config import OPENROUTER_BASE_URL, Settings, llm_endpoint

OK, FAIL, SKIP = "ok", "FAIL", "skip"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def mask(key: str) -> str:
    if not key:
        return "(not set)"
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else "set (short)"


def explain(err: BaseException, host: str) -> str:
    """Turn a failed request into a next step a person can take."""
    status = getattr(err, "status", None) or getattr(err, "code", None)
    text = str(err)
    if not isinstance(status, int) and (m := re.match(r"(\d{3}) ", text)):
        status = int(m.group(1))  # BodhanError messages start with the HTTP status
    if isinstance(err, urllib.error.URLError) and not isinstance(err, urllib.error.HTTPError):
        reason = str(err.reason)
        if "403" in reason or "Tunnel" in reason:
            return f"the network blocked {host}; add it to the environment's allowed domains"
        if isinstance(err.reason, socket.gaierror):
            return f"cannot resolve {host}; check the base URL and the network"
        return f"cannot reach {host}: {reason}"
    if isinstance(err, TimeoutError | socket.timeout):
        return f"{host} timed out; try again, or raise the timeout"
    if status in (401, 403) or "api key" in text.lower() or "unauthor" in text.lower():
        return "the key was rejected; check it was copied whole and belongs to this service"
    if status == 402 or "credit" in text.lower() or "balance" in text.lower():
        return "the account has no credit; redeem the coupon or add billing"
    if status == 404:
        return "model or endpoint not found; check AUTOASSESS_LLM_MODEL and the base URL"
    if status == 429:
        return "rate limited; wait a minute, or use a paid key for the demo"
    if "budget" in text.lower():
        return "the local budget guard stopped the call; raise BODHAN_BUDGET_INR"
    return ""


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


KEY_HELP = {
    "gemini": ("GEMINI_API_KEY or AUTOASSESS_LLM_API_KEY", "create one at aistudio.google.com/apikey"),
    "openrouter": ("OPENROUTER_API_KEY", "use the key the course emailed you"),
    "custom": ("AUTOASSESS_LLM_API_KEY", "set the key for AUTOASSESS_LLM_BASE_URL"),
}


def check_llm(settings: Settings, role: str = "LLM grader") -> Check:
    from autoassess.providers.llm import OpenAICompatibleLLM

    name = f"{role} [{settings.llm_provider}] ({settings.llm_model or 'no model'})"
    if not settings.llm_model:
        return Check(name, FAIL, "AUTOASSESS_LLM_MODEL is not set", "set it in .env, e.g. gemini-2.5-flash")
    if not settings.llm_api_key and "localhost" not in settings.llm_base_url:
        var, hint = KEY_HELP.get(settings.llm_provider, KEY_HELP["custom"])
        return Check(name, SKIP, f"{var} is not set", hint)
    llm = OpenAICompatibleLLM(settings.llm_base_url, settings.llm_model, settings.llm_api_key, cache=None, timeout=60)
    try:
        # Same request shape as grading: JSON mode and a seed.
        reply = llm.complete_json(
            "You are a health check. Reply with a JSON object only.",
            'Return {"ok": true, "sum": 2 + 3} with the sum computed.',
            seed=1,
        )
    except Exception as err:  # noqa: BLE001 - report every failure, never crash the doctor
        return Check(name, FAIL, str(err)[:300], explain(err, _host(settings.llm_base_url)))
    if reply.get("sum") != 5:
        return Check(name, FAIL, f"unexpected reply {reply!r}", "the model answered but not in the expected JSON")
    return Check(name, OK, f"JSON reply received from {_host(settings.llm_base_url)}")


def _test_page_png() -> bytes:
    """A small page with a line of text, so OCR has something to read."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("L", (900, 160), 255)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=44)
        except TypeError:  # Pillow < 10.1
            font = ImageFont.load_default()
        draw.text((30, 50), "Answer 1: a stack is LIFO", fill=0, font=font)
        import io

        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except ImportError:
        # Plain white page; OCR returns nothing, but the key and network are still exercised.
        w, h = 64, 16
        raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _ledger_path(settings: Settings) -> Path:
    return Path(settings.cache_dir) / "bodhan_ledger.json"


def check_bodhan_ocr(settings: Settings) -> Check:
    from autoassess.providers.bodhan import BodhanOCR, Ledger

    name = "Bodhan IndicOCR"
    if not settings.ocr_key:
        return Check(name, SKIP, "BODHAN_API_KEY / BODHAN_OCR_API_KEY not set", "create a key at console.bodhan.ai")
    ocr = BodhanOCR(settings.ocr_key, settings.bodhan_base_url, cache=None, budget_inr=settings.bodhan_budget_inr, timeout=90)
    ocr.client.ledger = Ledger(_ledger_path(settings), settings.bodhan_budget_inr)
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "doctor.png"
        img.write_bytes(_test_page_png())
        try:
            page = ocr.read_page(img, 0)
        except Exception as err:  # noqa: BLE001
            return Check(name, FAIL, str(err)[:300], explain(err, _host(ocr.client.base_url)))
    text = page.text.strip().replace("\n", " ")
    boxes = sum(1 for line in page.lines if line.bbox)
    return Check(name, OK, f"read {text[:60]!r}, {boxes} line boxes")


def check_bodhan_translate(settings: Settings) -> Check:
    from autoassess.providers.bodhan import BodhanTranslate, Ledger

    name = "Bodhan Indic-Translate"
    if not settings.translate_key:
        return Check(name, SKIP, "BODHAN_API_KEY / BODHAN_TRANSLATE_API_KEY not set", "create a key at console.bodhan.ai")
    tr = BodhanTranslate(settings.translate_key, settings.bodhan_base_url, cache=None, budget_inr=settings.bodhan_budget_inr, timeout=60)
    tr.client.ledger = Ledger(_ledger_path(settings), settings.bodhan_budget_inr)
    try:
        out = tr.translate("Good answer.", "Hindi")
    except Exception as err:  # noqa: BLE001
        return Check(name, FAIL, str(err)[:300], explain(err, _host(tr.client.base_url)))
    return Check(name, OK, f"'Good answer.' -> {out!r}")


def check_openrouter_credit(settings: Settings, timeout: float = 30) -> Check:
    """Key limit, spend and expiry from OpenRouter's GET /key (free, no tokens used)."""
    name = "OpenRouter credit"
    if not settings.openrouter_api_key:
        return Check(name, SKIP, "OPENROUTER_API_KEY not set", KEY_HELP["openrouter"][1])
    req = urllib.request.Request(f"{OPENROUTER_BASE_URL}/key", headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())["data"]
    except Exception as err:  # noqa: BLE001
        return Check(name, FAIL, str(err)[:300], explain(err, _host(OPENROUTER_BASE_URL)))
    usage, limit, left = data.get("usage") or 0.0, data.get("limit"), data.get("limit_remaining")
    parts = [f"used ${usage:.2f}"]
    parts.append(f"of ${limit:.2f} limit, ${left:.2f} left" if limit is not None and left is not None else "no key limit")
    if data.get("limit_reset"):
        parts.append(f"limit resets {data['limit_reset']}")
    parts.append(f"expires {data['expires_at']}" if data.get("expires_at") else "no expiry date on the key")
    detail = ", ".join(parts)
    if left is not None and left <= 0:
        return Check(name, FAIL, detail, "the key's credit is used up; ask the TAs or switch AUTOASSESS_LLM_PROVIDER")
    return Check(name, OK, detail)


def _standby_llms(settings: Settings) -> list[Settings]:
    """Hosted providers that have a key but are not the active one, so a switch is known to work."""
    out = []
    for provider in ("gemini", "openrouter"):
        if provider == settings.llm_provider:
            continue
        base, model, key = llm_endpoint(provider)
        if key:
            out.append(dataclasses.replace(settings, llm_provider=provider, llm_base_url=base, llm_model=model, llm_api_key=key))
    return out


def run_doctor(settings: Settings, paid: bool = True) -> list[Check]:
    checks = [check_llm(settings)]
    checks += [check_llm(s, role="standby LLM") for s in _standby_llms(settings)]
    if settings.openrouter_api_key:
        checks.append(check_openrouter_credit(settings))
    if paid:
        checks += [check_bodhan_ocr(settings), check_bodhan_translate(settings)]
    else:
        checks += [Check(n, SKIP, "skipped (--free)") for n in ("Bodhan IndicOCR", "Bodhan Indic-Translate")]
    return checks


def report(settings: Settings, checks: list[Check]) -> str:
    from autoassess.providers.bodhan import Ledger

    spent = Ledger(_ledger_path(settings), settings.bodhan_budget_inr).spent()
    lines = [
        "Configuration",
        f"  LLM          [{settings.llm_provider}] {settings.llm_base_url}  model={settings.llm_model or '(not set)'}  key={mask(settings.llm_api_key)}",
        f"  critic       {settings.critic_model or '(same as LLM)'}",
        f"  OpenRouter   key={mask(settings.openrouter_api_key)}",
        f"  OCR provider {settings.ocr_provider}",
        f"  Bodhan       {settings.bodhan_base_url}  ocr key={mask(settings.ocr_key)}  translate key={mask(settings.translate_key)}",
        f"  Bodhan spend Rs {spent:.2f} of Rs {settings.bodhan_budget_inr:g} budget",
        "",
        "Checks",
    ]
    for c in checks:
        lines.append(f"  [{c.status:>4}] {c.name}: {c.detail}")
        if c.hint and c.status != OK:
            lines.append(f"         -> {c.hint}")
    return "\n".join(lines)
