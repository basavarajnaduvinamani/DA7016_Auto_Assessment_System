"""Readable review signals and language metadata for teacher templates."""

LANGUAGE_CODES = {
    "English": "en",
    "Hindi": "hi",
    "Kannada": "kn",
    "Tamil": "ta",
    "Telugu": "te",
    "Marathi": "mr",
    "Bengali": "bn",
    "Malayalam": "ml",
    "Gujarati": "gu",
    "Odia": "or",
    "Punjabi": "pa",
}
FLAGS = {
    "possible_prompt_injection": (
        "Possible prompt injection",
        "Possible prompt injection: the answer contains instructions to the examiner",
    ),
    "low_ocr_confidence": (
        "Low reading confidence",
        "Low reading confidence: check the recognised text against the page",
    ),
    "examiners_disagree": ("Examiners disagree", "Examiners disagree: independent grading judgements differ"),
    "grader_disagreement": ("Examiners disagree", "Examiners disagree: repeated grading runs differ"),
    "unanswered": ("Unanswered", "Unanswered: no answer was recognised for this question"),
    "contains_diagram": ("Diagram present", "Diagram present: check visual work before accepting the mark"),
}


def language_code(language: str) -> str:
    """Resolve a supported language name or an existing ISO code for HTML metadata."""
    return LANGUAGE_CODES.get(language, language.lower().split("-")[0] if language else "en")


def flag_chips(flags: list[str]) -> list[dict[str, str]]:
    """Turn stored flags into accessible labels while retaining their machine identifiers."""
    chips = []
    for flag in dict.fromkeys(flags):
        key = flag.split(":", 1)[0]
        label, title = FLAGS.get(key, ("Marking notice", "Review this marking notice before accepting the answer"))
        if key == "unsupported_evidence":
            label, title = "Evidence needs review", "The proposed quote could not be verified in the answer"
        elif key == "inconsistent_with":
            label, title = "Examiners disagree", "Similar answers received different marks; compare the pair"
        elif key == "regraded":
            label, title = "AI re-check", "This criterion has an evidence-checked regrade decision"
        chips.append({"code": flag, "label": label, "title": title})
    return chips
