"""Content-addressed disk cache.

Every OCR and LLM call goes through this, so a page or prompt is never paid
for twice and runs are reproducible.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


def content_key(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            h.update(part)
        else:
            h.update(json.dumps(part, sort_keys=True, ensure_ascii=False, default=str).encode())
        h.update(b"\x00")
    return h.hexdigest()


class DiskCache:
    def __init__(self, root: str | Path, namespace: str):
        self.dir = Path(root) / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        p = self._path(key)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def set(self, key: str, value: Any) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def get_or_compute(self, key: str, fn: Callable[[], Any]) -> Any:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = fn()
        self.set(key, value)
        return value
