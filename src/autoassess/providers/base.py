"""Provider interfaces. The pipeline only ever talks to these.

Configured adapters implement the same contracts for local and hosted services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from autoassess.schemas import OCRPage


class OCRProvider(ABC):
    """Interface for reading page text, layout and recognition confidence."""

    name: str = "base"

    @abstractmethod
    def read_page(self, image_path: Path, page_index: int, language_hint: str | None = None) -> OCRPage:
        """Return the page's text as lines, with boxes and confidence when available."""


class LLMClient(ABC):
    """Interface for structured text and optional image-based model responses."""

    name: str = "base"

    @abstractmethod
    def complete_json(self, system: str, user: str, *, temperature: float = 0.0, seed: int | None = None) -> dict:
        """Return the model's reply parsed as a JSON object."""

    def complete_json_images(
        self, system: str, user: str, images: list[bytes], *, temperature: float = 0.0, seed: int | None = None
    ) -> dict:
        """Same, with page images (PNG or JPEG bytes) after the text. Vision models only."""
        raise NotImplementedError(f"{self.name} does not take images")


class Translator(ABC):
    """Interface for translating feedback while preserving its structure."""

    name: str = "base"

    @abstractmethod
    def translate(self, text: str, target_language: str, source_language: str = "English") -> str:
        """Translate text, keeping Markdown structure."""
