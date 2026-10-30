"""Public landing page content. Every number is copied from docs/report/numbers.md (checked by a test)."""

REPO_URL = "https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System"
NUMBERS_URL = REPO_URL + "/blob/main/docs/report/numbers.md"

# SPRAG test set, n = 455 typed short answers, 0-5 marks, two human graders.
RESULTS = [
    {"system": "Human vs human", "qwk": "0.962", "ci": "", "mae": "0.22", "within_1": "100%", "kind": "ceiling"},
    {"system": "Red-Ink Grader (final configuration)", "qwk": "0.723", "ci": "[0.667, 0.773]", "mae": "0.85", "within_1": "76%", "kind": "ours"},
    {"system": "Lexical baseline", "qwk": "0.375", "ci": "", "mae": "1.62", "within_1": "40%", "kind": "baseline"},
]

# Handwritten classroom set: 9 students x 15 two-mark questions, one teacher.
CLASSROOM = {"qwk": "0.47", "ci": "[0.32, 0.57]", "students": "9", "answers": "135", "flagged": "75 of 135"}

STEPS = [
    ("Write the rubric", "Questions, marks, a model answer and checkable criteria. A rubric check warns about vague points."),
    ("Upload the sheets", "Typed text, PDFs or phone photos. Handwriting is read with Bodhan IndicOCR, including Indian languages."),
    ("Grade every criterion with evidence", "Three grading runs, median marks. Each mark must quote the student's own words; code checks the quote is really there."),
    ("Flag what it is unsure about", "Run spread, OCR confidence and reviewer changes give a confidence. Low-confidence and suspicious answers go to you first."),
    ("Review, then release", "Accept or change a mark with a reason; the original AI mark is kept. Release red-ink marked sheets and export grades."),
]
