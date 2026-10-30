# 08: Presentation slides (Beamer)

Status: done
Depends on: 07 (same numbers)

## Goal

A 10-12 slide Beamer deck for a 10-minute talk plus live demo to the TAs over Google Meet.

## Files

- `docs/slides/main.tex`, `docs/slides/Makefile` (`make -C docs/slides` builds `main.pdf`). Reuse the report's TikZ pipeline figure. Add the build to the report CI workflow and upload the PDF as an artifact. Do not commit PDFs.

## Content (one idea per slide, numbers only from `docs/report/numbers.md`)

1. Title (same title/author/course as the report).
2. Problem and the bar: marks per question plus feedback specific enough to improve, no human in the loop by default.
3. Pipeline (TikZ figure): ingest, Bodhan OCR, segmentation, criterion grading x3 median, quote check, advocate, confidence, feedback, red ink.
4. Design choices that make marks defensible: verbatim evidence quotes checked in code, confidence-gated deferral to teacher, lenient policy.
5. Data: SPRAG and the handwritten classroom set; dev/test discipline.
6. Headline results table (SPRAG test): baseline, final config, human-human.
7. Ablation: the critic finding (small bar chart in pgfplots or a table).
8. Confidence gating: 62% auto-marked at MAE 0.66.
9. Handwritten set: what changes with real handwriting.
10. Robustness: prompt injection result and fix; Indic example.
11. Limitations and next steps.
12. Demo: what will be shown live (sample sheet -> red-ink PDF -> regrade request).

## Done when

- Builds with standard TeX Live; text is readable at 1280x720 (no font under 14pt for body text).
- `pytest -q` passes.
