# 13: Teacher app: Indic feedback, robustness signals and UI polish

Status: todo
Depends on: 12 can run in parallel; merge after 12 if both touch the same files

## Why

The course grades "Robustness and Multilingual Capabilities" (adversarial inputs, edge cases, Indic languages) and "User Interface and Experience" (bonus for design beyond default generated interfaces). The engine supports feedback translation (Bodhan Indic-Translate) and flags prompt injection, but the teacher app does not expose either.

## Do

1. **Feedback language per assignment.** On the new-assignment form add "Feedback language" (English plus the 10 Indian languages in `autoassess.demo.LANGUAGES`, default English). Store it with the assignment; grading jobs pass it through `Options.language` (translation happens only when a Bodhan translate key is configured; otherwise show a one-line notice on the assignment page "Feedback stays in English: translation is not configured"). The review answer page shows the translated feedback with the English original under a "Show English" toggle.
2. **Answer language.** The answer page renders Devanagari, Kannada, Tamil etc. correctly (font stack with Noto Sans fallbacks, `lang` attribute from the assignment's language).
3. **Robustness signals visible.** In the review queue and answer page, show each flag as a readable chip with a tooltip: "Possible prompt injection: the answer contains instructions to the examiner", "Low reading confidence", "Examiners disagree", "Unanswered", "Diagram present". Flagged rows sort first (already) and show the chip in the list. A filter "Show: all / flagged / injection" on the queue.
4. **Edge cases.** Friendly errors (no stack traces) for: empty upload, unsupported file type, file over the size limit, a sheet with no recognisable questions (grade completes with all questions "unanswered" and a notice), duplicate roll numbers in a roster CSV, a rubric whose criteria marks do not add up to the question marks (lint warning shown before saving). Tests for each.
5. **UI polish.** Keep the existing red-ink identity. Add: an empty-state illustration/text on dashboard and review queue; a small "how marking works" panel on the assignment page (3 steps, plain words); a visible marked-sheet thumbnail on the answer page (first page PNG) with a link to the full PDF; keyboard hint line in the review queue (J/K/A). No new JS framework.

## Done when

- Tests: assignment saves language; grading passes it to `Options.language` (fake translator in tests); translated and English feedback both stored and rendered; flag chips render; each edge case returns a friendly message with the right status code. `pytest -q` and `ruff check .` pass.
- Screenshots of dashboard, review queue (with an injection chip) and a Hindi-feedback answer page attached to the PR description.

## Out of scope

Student accounts, real authentication, new grading logic.
