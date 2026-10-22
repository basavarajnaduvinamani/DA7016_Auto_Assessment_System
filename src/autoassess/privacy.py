"""Privacy: what leaves the machine, and where it may go.

- anonymise() removes names, roll numbers, register numbers, emails and phone
  numbers from text before any LLM call. Answer text is otherwise unchanged,
  so evidence quotes still match.
- check_provider_for_real_sheets() refuses free-tier LLM endpoints when
  AUTOASSESS_REAL_SHEETS=1: Google's free Gemini tier may use prompts for
  training, so real students' answers go only to a paid key (the course's
  OpenRouter key, or paid Gemini).
"""

from __future__ import annotations

import re

_FIELD = re.compile(
    r"(?im)^(?P<label>\s*(?:student\s*)?(?:name|roll\s*(?:no\.?|number)|reg(?:istration|ister)?\.?\s*(?:no\.?|number)"
    r"|usn|enrol(?:l)?ment\s*(?:no\.?|number)|admission\s*(?:no\.?|number)|seat\s*(?:no\.?|number)|candidate"
    r"|ಹೆಸರು|नाम|अनुक्रमांक)\s*[:\-–]\s*)(?P<value>[^\n]*)$"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
_ROLL = re.compile(r"\b(?:[A-Z]{2,4}\d{2}[A-Z]{1,4}\d{2,4}|\d{2}[A-Z]{2,4}\d{3,5})\b")  # e.g. 1RV22CS045, CS21B1045


def anonymise(text: str) -> str:
    text = _FIELD.sub(lambda m: f"{m.group('label')}[redacted]", text)
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    return _ROLL.sub("[id]", text)


FREE_TIER_HOSTS = ("generativelanguage.googleapis.com",)


class PrivacyError(RuntimeError):
    pass


def check_provider_for_real_sheets(base_url: str | None, real_sheets: bool, paid_gemini: bool = False) -> None:
    if not real_sheets or paid_gemini:
        return
    if base_url and any(h in base_url for h in FREE_TIER_HOSTS):
        raise PrivacyError(
            "AUTOASSESS_REAL_SHEETS=1 but the LLM is the free Gemini tier, which may use prompts for training. "
            "Set AUTOASSESS_LLM_PROVIDER=openrouter, or AUTOASSESS_GEMINI_PAID=1 if the key is on a billed project."
        )
