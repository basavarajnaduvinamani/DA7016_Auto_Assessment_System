"""LLM client for any OpenAI-compatible chat endpoint (Ollama, vLLM, hosted APIs).

Uses only the standard library so the core install stays small. Every call is
cached on (model, messages, temperature, seed).
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request

from autoassess.budget import Ledger, record_llm_cost
from autoassess.cache import DiskCache, content_key
from autoassess.providers.base import LLMClient

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_reply(text: str) -> dict:
    """Parse a model reply that should be a JSON object, tolerating code fences."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(cleaned[start : end + 1])


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OpenAICompatibleLLM(LLMClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        cache: DiskCache | None = None,
        timeout: float = 120,
        ledger: Ledger | None = None,
    ):
        if not model:
            raise ValueError("no LLM model configured; set AUTOASSESS_LLM_MODEL")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.cache = cache
        self.timeout = timeout
        self.ledger = ledger
        self.name = f"openai-compatible:{model}"
        # Gemini's OpenAI-compatible endpoint rejects "seed" with a 400.
        self.sends_seed = "generativelanguage.googleapis.com" not in self.base_url

    def _post(self, payload: dict, retries: int = 5) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            if err.code in (429, 502, 503) and retries > 0:
                # Rate limit or a provider hiccup: back off 4, 8, 16, 32, 64 seconds.
                time.sleep(4 * 2 ** (5 - retries))
                return self._post(payload, retries - 1)
            body = err.read().decode(errors="replace")
            try:
                detail = json.loads(body)
                detail = (detail[0] if isinstance(detail, list) else detail)["error"]["message"]
            except (ValueError, KeyError, TypeError, IndexError):
                detail = body[:300] or err.reason
            raise LLMError(f"{err.code} from {self.base_url}: {detail}", err.code) from err

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0, seed: int | None = None) -> dict:
        return self._complete(system, user, temperature, seed)

    def complete_json_images(
        self, system: str, user: str, images: list[bytes], *, temperature: float = 0.0, seed: int | None = None
    ) -> dict:
        content: list[dict] = [{"type": "text", "text": user}]
        for img in images:
            mime = "image/jpeg" if img[:3] == b"\xff\xd8\xff" else "image/png"
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(img).decode()}"}})
        return self._complete(system, content, temperature, seed)

    def _complete(self, system: str, user: str | list[dict], temperature: float, seed: int | None) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if seed is not None:
            payload["seed"] = seed

        def call() -> str:
            # The seed stays in the cache key either way, so repeated runs are cached separately.
            sent = payload if self.sends_seed else {k: v for k, v in payload.items() if k != "seed"}
            if self.ledger:
                self.ledger.check()
            response = self._post(sent)
            record_llm_cost(self.ledger, response)
            return response["choices"][0]["message"]["content"]

        # A malformed reply is cached too, so each new attempt gets its own cache key.
        for attempt in range(3):
            key = payload if attempt == 0 else {**payload, "retry": attempt}
            reply = call() if self.cache is None else self.cache.get_or_compute(content_key("llm", key), call)
            try:
                return parse_json_reply(reply)
            except ValueError:
                if attempt == 2:
                    raise
