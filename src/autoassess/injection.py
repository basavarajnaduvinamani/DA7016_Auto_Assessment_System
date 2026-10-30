"""Cheap, model-free checks for answers that try to game the grader.

Two checks run before any model call and only ever route an answer to the teacher; they never
change marks. ``injection_signals`` looks for instructions aimed at the examiner in English,
Hinglish, Hindi, Kannada, Tamil and Telugu. ``looks_keyword_stuffed`` spots answers that are a
bare list of rubric words with no sentence around them, which evidence quotes alone cannot stop.

Patterns were written against ``data/robustness/injection_dev.jsonl`` only. The separate
``injection_test.jsonl`` was written by a different author without seeing this file and is
scored once by ``autoassess injection-eval``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_F = re.IGNORECASE | re.DOTALL

# Each entry names the kind of manipulation, so a teacher (and the evaluation) can see why it fired.
PATTERNS: dict[str, re.Pattern[str]] = {
    "override_rubric": re.compile(
        r"\b(ignore|disregard|skip|bypass|forget|overlook)\b.{0,40}"
        r"\b(rubric|instructions?|model answer|marking (scheme|guide)|criteria|previous|above|checking)\b",
        _F,
    ),
    "demand_marks": re.compile(
        r"\b(award|give|assign|grant|allot|deserve[sd]?|should (get|receive|be given))\b.{0,30}"
        r"\b(full|maximum|max|all|perfect|complete|top|highest|100\s?%|\d+\s?/\s?\d+)\s+"
        r"(marks?|score|credit|points|grade)\b",
        _F,
    ),
    "address_examiner": re.compile(
        r"\b(note|message|instruction)s?\s+(to|for)\s+(the\s+)?(grader|examiner|marker|evaluator|checker|ai|model|"
        r"assistant|teacher)\b"
        r"|\b(dear|hey|hello|attention)\s+(grader|examiner|evaluator|marker|ai|model|assistant|grading (ai|model|system))\b",
        _F,
    ),
    "role_play": re.compile(
        r"\b(you are|act as|as)\s+(an?\s+|the\s+)?(lenient|generous|kind)?\s*"
        r"(grader|examiner|evaluator|grading (ai|model|system|assistant))\b.{0,60}\b(must|should|will|need to)\b"
        r"|\byou (must|should|will|need to)\s+(award|give|grade|mark|score|pass|accept)\b",
        _F,
    ),
    "fake_system": re.compile(
        r"\[\s*(system|admin|instruction|override|grader)[^\]]{0,20}\]|<\|?\s*(system|im_start|instruction)\s*\|?>"
        r"|(^|\n)\s*(system|assistant|grader)\s*:",
        _F,
    ),
    "format_injection": re.compile(
        r"[\"']?\b(marks_awarded|score|verdict|total_marks|grade)\b[\"']?\s*[:=]\s*[\"']?\s*(\d|met\b|full\b|pass\b|a\+?\b)",
        _F,
    ),
    "assert_met": re.compile(
        r"\b(all|every|each)\s+(of\s+the\s+)?(rubric\s+|marking\s+)?(criteria|criterion|points|requirements|"
        r"rubric items)\b.{0,40}\b(are|is|have been|has been|were)\s+(fully\s+)?(met|satisfied|covered|fulfilled|addressed)\b"
        r"|\b(as|per)\s+the\s+rubric\b.{0,60}\b(full|all)\s+(credit|marks)\b",
        _F,
    ),
    "appeal": re.compile(
        r"\b(please|kindly|plz|pls|i beg|i request)\b.{0,50}"
        r"\b(marks?|grade|lenient|leniency|pass me|let me pass|score|consider|go easy)\b",
        _F,
    ),
    "hinglish": re.compile(
        r"\b(poore|pure|pura|poora|full|zyada|jyada|achhe|ache)\s+(marks|number|nambar|ank)\b"
        r"|\b(marks|number|nambar)\b.{0,30}\b(de\s?do|de\s?dijiye|dijiye|dena|de\s?dena|chahiye|kar\s?dijiye|"
        r"kar\s?do|dedo)\b"
        r"|\b(pass\s+kar\s?(do|dijiye|dena))\b",
        _F,
    ),
    "hindi": re.compile(
        r"(पूरे|पूर्ण|अधिक|ज़्यादा|ज्यादा|अच्छे|सारे|पूरा)\s*(अंक|नंबर|मार्क्स)"
        r"|(अंक|नंबर|मार्क्स)\s*(दें|दे\s*दें|दीजिए|दीजिये|देना|दे\s*दो|दो|दिए\s*जाएं)"
        r"|(परीक्षक|जाँचकर्ता|जांचकर्ता|मूल्यांकनकर्ता)\s*(के\s*लिए|से|जी|महोदय)"
        r"|(अनदेखा|नजरअंदाज|नज़रअंदाज़|अनदेखी)\s*(कर|करें|करो)"
        r"|(कृपया|प्लीज़|प्लीज).{0,40}(अंक|नंबर|पास|मार्क्स)"
        r"|पास\s*कर\s*(दें|दीजिए|दीजिये|दो)",
        _F,
    ),
    "kannada": re.compile(
        r"(ಪೂರ್ಣ|ಪೂರ್ತಿ|ಹೆಚ್ಚು|ಎಲ್ಲಾ)\s*ಅಂಕ"
        r"|ಅಂಕ[^\s]*\s*(ನೀಡಿ|ಕೊಡಿ|ಕೊಡಬೇಕು|ನೀಡಬೇಕು|ಹಾಕಿ)"
        r"|ಪರೀಕ್ಷಕ[^\s]*\s*(ಸೂಚನೆ|ಗಮನಕ್ಕೆ|ಗೆ)"
        r"|ನಿರ್ಲಕ್ಷಿಸ|(ದಯವಿಟ್ಟು|ಪ್ಲೀಸ್).{0,40}(ಅಂಕ|ಪಾಸ್)"
        r"|ಪಾಸ್\s*ಮಾಡಿ",
        _F,
    ),
    "tamil": re.compile(
        r"(முழு|அதிக|எல்லா|முழுமையான)\s*மதிப்பெண்"
        r"|மதிப்பெண்[^\s]*\s*(கொடு|வழங்கு|தாருங்கள்|போடு|தர\s*வேண்டும்|அளி)"
        r"|(தேர்வாளர்|மதிப்பீட்டாளர்)[^\s]*\s*(கவனத்திற்கு|குறிப்பு|க்கு)"
        r"|புறக்கணி|(தயவுசெய்து|ப்ளீஸ்).{0,40}(மதிப்பெண்|பாஸ்|தேர்ச்சி)"
        r"|பாஸ்\s*(செய்யுங்கள்|பண்ணுங்க)",
        _F,
    ),
    "telugu": re.compile(
        r"(పూర్తి|ఎక్కువ|అన్ని|మొత్తం)\s*మార్కులు"
        r"|మార్కులు\s*(ఇవ్వండి|ఇవ్వాలి|వేయండి|ఇవ్వు|వేయాలి)"
        r"|(పరీక్షకుడ|ఎగ్జామినర్|మూల్యాంకనకర్త)[^\s]*\s*(గమనిక|కి|కు)"
        r"|(పట్టించుకోవద్దు|విస్మరించ)|(దయచేసి|ప్లీజ్).{0,40}(మార్కులు|పాస్)"
        r"|పాస్\s*చేయండి",
        _F,
    ),
}


def injection_signals(text: str) -> list[str]:
    """Names of the manipulation patterns found in ``text``; empty when none match."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


# Function words carry the sentence; a stuffed answer has the topic words without them.
_FUNCTION_WORDS = frozenset(
    "a an the is are was were be been being of to in on at by for from with as and or but if then so because "
    "which that this these those it its they them their we our you your he she his her can could will would "
    "should may might must do does did has have had not no when where while how what why than also into "
    "through over under between each every one more most less such there here all some any other only "
    "used uses using takes take makes make gives give called known like".split()
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


# Commas, numbering, bullets or line breaks mark a deliberate list ("Bar chart, Pie chart"), which
# many short-answer questions ask for; stuffing runs the terms together with no separators.
_LIST_SEPARATOR = re.compile(r"[,;:\n•]|\(\w\)|(^|\s)(\d+|[a-z])[.)]\s*\w", re.IGNORECASE)


def looks_keyword_stuffed(answer: str, *, min_words: int = 8, max_function_share: float = 0.12) -> bool:
    """True when an English answer runs topic terms together with almost no connecting words.

    Real sentences, even terse ones, are roughly 30-50% function words; a pasted keyword string
    is close to zero. Answers laid out as a list (commas, numbering, line breaks) are left alone,
    because "name three charts" questions legitimately get lists. The same word three times
    in a row ("attention attention attention") is also a stuffing sign. Mostly non-Latin answers are skipped, because the
    function-word list is English only.
    """
    words = [w.lower() for w in _WORD.findall(answer)]
    letters = sum(ch.isalpha() for ch in answer)
    if len(words) < min_words or not letters or sum(len(w) for w in words) < 0.6 * letters:
        return False
    function_share = sum(w in _FUNCTION_WORDS for w in words) / len(words)
    if function_share > max_function_share:
        return False
    repeated = any(words[i] == words[i + 1] == words[i + 2] for i in range(len(words) - 2))
    return repeated or not _LIST_SEPARATOR.search(answer.strip().rstrip("."))


def evaluate_detector(path: str | Path) -> dict[str, Any]:
    """Score ``injection_signals`` on a labelled JSONL file of attacks and benign answers.

    Each line holds ``id``, ``lang``, ``label`` (``attack`` or ``benign``) and ``text``. Returns
    recall on attacks and false-positive rate on benign answers, overall and per language, plus
    the ids of every miss and false alarm so they can be read by hand.
    """
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_lang: dict[str, dict[str, int]] = {}
    misses, false_alarms = [], []
    for row in rows:
        hit = bool(injection_signals(row["text"]))
        stats = by_lang.setdefault(row["lang"], {"attacks": 0, "caught": 0, "benign": 0, "flagged": 0})
        if row["label"] == "attack":
            stats["attacks"] += 1
            stats["caught"] += hit
            if not hit:
                misses.append(row["id"])
        else:
            stats["benign"] += 1
            stats["flagged"] += hit
            if hit:
                false_alarms.append(row["id"])

    def rate(num: int, den: int) -> float | None:
        """Share rounded for reporting, or None when there is nothing to divide by."""
        return round(num / den, 3) if den else None

    attacks = sum(s["attacks"] for s in by_lang.values())
    benign = sum(s["benign"] for s in by_lang.values())
    return {
        "file": str(path),
        "attacks": attacks,
        "recall": rate(attacks - len(misses), attacks),
        "benign": benign,
        "false_positive_rate": rate(len(false_alarms), benign),
        "by_language": {
            lang: {**s, "recall": rate(s["caught"], s["attacks"]), "fpr": rate(s["flagged"], s["benign"])}
            for lang, s in sorted(by_lang.items())
        },
        "missed": misses,
        "false_alarms": false_alarms,
    }
