"""Provider registry: pick implementations by config name."""

from __future__ import annotations

from autoassess.cache import DiskCache
from autoassess.config import Settings
from autoassess.providers.base import LLMClient, OCRProvider, Translator
from autoassess.providers.text_ocr import PlainTextOCR


def make_ocr(settings: Settings) -> OCRProvider:
    if settings.ocr_provider == "text":
        return PlainTextOCR()
    if settings.ocr_provider == "indic-local":
        from autoassess.providers.indic_ocr import IndicOCRLocal

        return IndicOCRLocal(settings.indic_ocr_repo or None)
    if settings.ocr_provider == "indic-precomputed":
        from autoassess.providers.indic_ocr import PrecomputedOCR

        return PrecomputedOCR(settings.ocr_json_dir)
    if settings.ocr_provider == "vision":
        from autoassess.providers.vision_llm import VisionLLMOCR

        return VisionLLMOCR(
            settings.llm_base_url,
            settings.vision_model,
            settings.llm_api_key,
            DiskCache(settings.cache_dir, "ocr"),
            ledger=settings.llm_ledger(),
        )
    if settings.ocr_provider == "bodhan":
        from autoassess.providers.bodhan import BodhanOCR

        return BodhanOCR(
            settings.ocr_key, settings.bodhan_base_url, DiskCache(settings.cache_dir, "ocr"), settings.bodhan_budget_inr
        )
    raise ValueError(f"unknown OCR provider {settings.ocr_provider!r}")


def make_llm(settings: Settings, critic: bool = False, model: str | None = None) -> LLMClient:
    """The grading model, the critic model (defaults to the grading model), or any named model."""
    from autoassess.privacy import check_provider_for_real_sheets
    from autoassess.providers.llm import OpenAICompatibleLLM

    check_provider_for_real_sheets(settings.llm_base_url, settings.real_sheets, settings.gemini_paid)
    model = model or ((settings.critic_model or settings.llm_model) if critic else settings.llm_model)
    return OpenAICompatibleLLM(
        settings.llm_base_url, model, settings.llm_api_key, DiskCache(settings.cache_dir, "llm"), ledger=settings.llm_ledger()
    )


def make_translator(settings: Settings) -> Translator:
    from autoassess.providers.bodhan import BodhanTranslate

    return BodhanTranslate(
        settings.translate_key, settings.bodhan_base_url, DiskCache(settings.cache_dir, "translate"), settings.bodhan_budget_inr
    )


__all__ = ["LLMClient", "OCRProvider", "Translator", "make_llm", "make_ocr", "make_translator"]
