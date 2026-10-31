"""Public landing page content: the product story, how it works and the supported languages."""

REPO_URL = "https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System"

NAME = "Second Read"
TAGLINE = "A little less checking, a little more teaching."
PROMISE = "The AI reads every answer first. You give the second read."

# The teacher's workflow in three steps; the order mirrors the app's assignment page.
STEPS = [
    (
        "Upload the rubric and the sheets",
        "Questions, marks and a model answer, then typed text, PDFs or phone photos of handwritten booklets.",
    ),
    (
        "Every criterion marked with evidence",
        "Each mark quotes the student's own words, and the quote is checked against the answer. No quote, no mark.",
    ),
    (
        "You give the second read, then countersign",
        "Unsure answers and the gaps your class shares come to you first. Change any mark with a reason, then release.",
    ),
]

# What sets the product apart, in the order a teacher asks about it.
FEATURES = [
    (
        "Evidence for every mark",
        "Students see the exact words that earned each point, and a concrete next step for each point they missed.",
    ),
    (
        "Knows when to ask you",
        "Low confidence, unclear handwriting, attempts to instruct the grader and keyword lists are handed back to you.",
    ),
    (
        "Your decision is final",
        "Every change is recorded with your reason, the original AI mark is kept, and each booklet is stamped AI-marked.",
    ),
]

# English plus the Indian languages offered for feedback (autoassess.demo.LANGUAGES), in their own scripts.
LANGUAGE_NAMES = [
    ("English", "en"),
    ("हिन्दी", "hi"),
    ("ಕನ್ನಡ", "kn"),
    ("தமிழ்", "ta"),
    ("తెలుగు", "te"),
    ("मराठी", "mr"),
    ("বাংলা", "bn"),
    ("മലയാളം", "ml"),
    ("ગુજરાતી", "gu"),
    ("ଓଡ଼ିଆ", "or"),
    ("ਪੰਜਾਬੀ", "pa"),
]


def privacy_note() -> dict[str, object]:
    """What the app stores, where and for how long, for the sign-in page, /privacy and the account page.

    The hosting line and the pilot end date come from AUTOASSESS_DATA_LOCATION and
    AUTOASSESS_PILOT_END, so the note matches the deployment it is shown on.
    """
    import os

    location = os.getenv("AUTOASSESS_DATA_LOCATION", "").strip() or (
        "the app server and its Postgres database" if os.getenv("DATABASE_URL") else "the app server"
    )
    end = os.getenv("AUTOASSESS_PILOT_END", "").strip()
    return {
        "short": (
            f"We store your email, your class rosters, the sheets you upload and their marks, in {location}. "
            "Sheets are sent to our AI and handwriting-reading services only to mark them. "
            "You can delete everything yourself at any time"
            + (f", and the rest is deleted when the pilot ends on {end}." if end else ".")
        ),
        "sections": [
            (
                "What we store",
                "Your name and email. The classes and rosters you add (student names and roll numbers). "
                "The answer sheets you upload, the text read from them, the AI's marks and feedback, and the "
                "marked PDFs. Every decision you make (accept or change a mark, with your reason) and when you "
                "opened and decided each answer, which is how review time is measured.",
            ),
            (
                "Where it is",
                f"In {location}. To mark a sheet, its pages or text are sent to the AI grading service "
                "(OpenRouter, using Google Gemini) and, for handwritten pages, to Bodhan IndicOCR; feedback in "
                "Indian languages is translated by Bodhan. Your roster is not sent to them.",
            ),
            (
                "How long",
                "Until you press Delete all my data on your Account page, which removes your account, classes, "
                "rosters, sheets, marks, files and logs straight away"
                + (f". Anything left is deleted when the pilot ends on {end}." if end else ".")
                + " Sign-in codes are kept only as a hash and expire after 10 minutes; sign-in rate-limit "
                "records are deleted after 24 hours.",
            ),
            (
                "What the pilot report contains",
                "Counts and timings only: minutes per sheet, how often you changed a mark and the average size "
                "of the change. No student names, roll numbers, answers, feedback or your reasons.",
            ),
        ],
    }
