"""Public landing page content: the product story, how it works and the supported languages."""

REPO_URL = "https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System"

NAME = "Second Read"
TAGLINE = "A little less checking, a little more teaching."
PROMISE = "The AI reads every answer first. You give the second read to the ones that need you."

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
