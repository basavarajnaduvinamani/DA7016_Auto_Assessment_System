"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# LLM providers. All speak the OpenAI chat API; AUTOASSESS_LLM_PROVIDER picks one.
#   gemini:     free tier for development (key from aistudio.google.com/apikey)
#   openrouter: the course's $20 key, for evaluation runs and the demo
#   custom:     any other endpoint in AUTOASSESS_LLM_BASE_URL (Ollama, vLLM)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "google/gemini-2.5-flash"
LLM_PROVIDERS = ("gemini", "openrouter", "custom")


def _env(name: str, default: str = "") -> str:
    """An empty value in .env counts as unset."""
    return os.getenv(name) or default


def llm_provider_from_env() -> str:
    """Explicit choice, else the first provider with a key (Gemini first: it is free)."""
    if provider := _env("AUTOASSESS_LLM_PROVIDER").lower():
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"AUTOASSESS_LLM_PROVIDER must be one of {', '.join(LLM_PROVIDERS)}, not {provider!r}")
        return provider
    if _env("AUTOASSESS_LLM_BASE_URL"):
        return "custom"
    if _env("GEMINI_API_KEY") or _env("AUTOASSESS_LLM_API_KEY"):
        return "gemini"
    if _env("OPENROUTER_API_KEY"):
        return "openrouter"
    return "gemini"


def llm_endpoint(provider: str) -> tuple[str, str, str]:
    """(base URL, model, key) for a provider. AUTOASSESS_LLM_MODEL overrides the model for any provider."""
    model = _env("AUTOASSESS_LLM_MODEL")
    if provider == "gemini":
        key = _env("GEMINI_API_KEY") or _env("AUTOASSESS_LLM_API_KEY")
        return GEMINI_BASE_URL, model or _env("GEMINI_MODEL", GEMINI_DEFAULT_MODEL), key
    if provider == "openrouter":
        return OPENROUTER_BASE_URL, model or _env("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL), _env("OPENROUTER_API_KEY")
    return _env("AUTOASSESS_LLM_BASE_URL", "http://localhost:11434/v1"), model, _env("AUTOASSESS_LLM_API_KEY")


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
    llm_provider: str = field(default_factory=llm_provider_from_env)
    # Left as None, these three come from llm_endpoint(llm_provider).
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    critic_model: str = field(default_factory=lambda: os.getenv("AUTOASSESS_CRITIC_MODEL", ""))
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    bodhan_api_key: str = field(default_factory=lambda: os.getenv("BODHAN_API_KEY", ""))
    # Bodhan may issue one key per model; each falls back to BODHAN_API_KEY.
    bodhan_ocr_api_key: str = field(default_factory=lambda: os.getenv("BODHAN_OCR_API_KEY", ""))
    bodhan_translate_api_key: str = field(default_factory=lambda: os.getenv("BODHAN_TRANSLATE_API_KEY", ""))
    bodhan_base_url: str = field(default_factory=lambda: os.getenv("BODHAN_BASE_URL", "https://api.bodhan.ai"))
    # Course credits: Rs 110 on Bodhan and $20 on OpenRouter; the guards stop a little short of both.
    bodhan_budget_inr: float = field(default_factory=lambda: float(_env("BODHAN_BUDGET_INR", "100")))
    openrouter_budget_usd: float = field(default_factory=lambda: float(_env("OPENROUTER_BUDGET_USD", "18")))

    def __post_init__(self) -> None:
        base, model, key = llm_endpoint(self.llm_provider)
        self.llm_base_url = base if self.llm_base_url is None else self.llm_base_url
        self.llm_model = model if self.llm_model is None else self.llm_model
        self.llm_api_key = key if self.llm_api_key is None else self.llm_api_key

    def llm_ledger(self):
        """Spend guard for the LLM: only OpenRouter costs money (Gemini free tier, local models)."""
        from autoassess.budget import openrouter_ledger

        if self.llm_base_url and self.llm_base_url.startswith(OPENROUTER_BASE_URL):
            return openrouter_ledger(self.cache_dir, self.openrouter_budget_usd)
        return None

    @property
    def ocr_key(self) -> str:
        return self.bodhan_ocr_api_key or self.bodhan_api_key

    @property
    def translate_key(self) -> str:
        return self.bodhan_translate_api_key or self.bodhan_api_key

    @classmethod
    def load(cls) -> Settings:
        _load_dotenv()
        return cls()
