"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


@dataclass
class Settings:
    cache_dir: Path = field(default_factory=lambda: Path(os.getenv("AUTOASSESS_CACHE_DIR", ".cache")))
    ocr_provider: str = field(default_factory=lambda: os.getenv("AUTOASSESS_OCR_PROVIDER", "text"))
    ocr_json_dir: Path = field(default_factory=lambda: Path(os.getenv("AUTOASSESS_OCR_JSON_DIR", "ocr_json")))
    indic_ocr_repo: str = field(default_factory=lambda: os.getenv("AUTOASSESS_INDIC_OCR_REPO", ""))
    vision_model: str = field(default_factory=lambda: os.getenv("AUTOASSESS_VISION_MODEL", ""))
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("AUTOASSESS_LLM_BASE_URL", "http://localhost:11434/v1")
    )
    llm_model: str = field(default_factory=lambda: os.getenv("AUTOASSESS_LLM_MODEL", ""))
    critic_model: str = field(default_factory=lambda: os.getenv("AUTOASSESS_CRITIC_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("AUTOASSESS_LLM_API_KEY", ""))
    bodhan_api_key: str = field(default_factory=lambda: os.getenv("BODHAN_API_KEY", ""))
    bodhan_base_url: str = field(
        default_factory=lambda: os.getenv("BODHAN_BASE_URL", "https://api.bodhan.ai/v1")
    )

    @classmethod
    def load(cls) -> Settings:
        _load_dotenv()
        return cls()
