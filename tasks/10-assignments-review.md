# 10: Teacher web app, part 2: assignments, uploads, grading, review queue

Status: todo
Depends on: 09

## Goal

The core loop from the concept doc: set up an assignment, upload a pile of sheets, grade them in the background, review flagged answers first, release.

## Reuse (do not reimplement)

`autoassess.demo.mark_sheet` / `validate_upload` / `demo_settings` / `llm_available`, `autoassess.spec_builder.load_spec` / `lint_spec` / `draft_spec`, `autoassess.classwork.grade_class`, `autoassess.regrade.regrade`, the annotator output (marked PDF and page PNGs), `SheetGrade` JSON as stored output. Grading defaults are whatever task 07 made the default (advocate only).

## Screens

1. **New assignment** (`/classes/{id}/assignments/new`): title; questions added one by one (question text, max marks, criteria rows with description and marks, optional model answer); "Import rubric (YAML/JSON)" as an alternative; "Suggest criteria" button that calls `draft_spec` on the question and model answer (only when an LLM is available). Saving builds an `ExamSpec`, runs `lint_spec`, shows warnings inline, and stores the spec JSON.
2. **Upload** (`/assignments/{id}/upload`): drop many files (.pdf, .png, .jpg, .jpeg, .txt; existing size limits). Match each file to a student: by roll number in the file name first (e.g. `S003.pdf`, `S003_scan.pdf`), otherwise a "Needs matching" list with a student dropdown. (OCR of the cover page is a stretch goal; skip if short of time.)
3. **Grading progress**: "Grade all" starts a background job (a `ThreadPoolExecutor` with 2 workers, job rows in SQLite: queued, running, done, failed + message). The assignment page polls with htmx every 2 s and shows a progress bar and per-sheet status. A failed sheet shows a readable reason and a "Retry" button. Grading survives a page reload; jobs left `running` at startup are reset to `queued`.
4. **Review queue** (`/assignments/{id}/review`): one row per (student, question), flagged answers first (needs_review, low_ocr_confidence, possible_prompt_injection), then the rest. Opening a row shows the page image or answer text beside each criterion's marks, evidence quote, reason and feedback. Actions: "Accept" (one click), "Change mark" (new value + required reason; both versions kept in an `overrides` table and applied to exports), "Re-check with AI" (calls `regrade` with the teacher's reason). Keyboard: J/K next/previous, A accept.
5. **Assignment page**: counts (uploaded, graded, needs review, accepted), class average, buttons to review and release. "Release" is enabled when nothing needs review (or the teacher confirms releasing anyway); released sheets show their marked PDF link.
6. Dashboard cards show "N answers need review" from real data.

## Seed

Extend the demo class with one assignment using the sample rubric and the four packaged sample sheets (S001-S003 `.txt`, `S002_scan.pdf` only if OCR is configured), pre-graded with the fake provider on first start so the review queue is never empty in a demo.

## Done when

- End-to-end test with the fake LLM provider: sign in, create assignment from the form, upload 3 sample sheets, grade all, see flagged items, accept one, change one with a reason, release. Plus unit tests for file-to-student matching, job state transitions and override application. `pytest -q` passes.
- No grading code in `src/autoassess/` outside `web/` changes, except small, tested hooks if unavoidable (explain them in the PR).

## Out of scope

Exports, class report page and deployment (task 11); student-facing pages.
