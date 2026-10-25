# 03: Final report skeleton (LaTeX)

Status: done
Depends on: 02 (uses its `tables/*.tex` and `figures/*.png` names)

## Goal

A complete, compilable final project report whose prose describes the system as built, with every number pulled in from the results pack, so filling in results later is only re-running commands.

## Files

- New `docs/report/main.tex`, `docs/report/sections/*.tex`, `docs/report/Makefile`.
- `docs/report/references.bib`: start from `docs/archive/references.bib` (copy, don't edit the archive) and add entries you cite.
- `docs/report/results/`: placeholder copies of each `tables/*.tex` (a one-row table reading "pending") and placeholder PNGs (a blank image with "pending"), so it compiles before real results exist. The Makefile target `results` copies `runs/results/tables` and `runs/results/figures` over them.
- `.github/workflows/report.yml`: compiles the PDF with a LaTeX action on changes under `docs/report/` and uploads it as an artifact. Do not commit the PDF.

## Content

Article class, 8 to 10 pages. Title "Auto-Assessment: Rubric-Grounded Grading of Handwritten Answer Sheets with Red-Ink Feedback", author Basavaraj A Naduvinamani (DA25C005), course DA7016, IIT Madras. Sections:

1. Introduction: the problem, the bar ("feedback specific enough for a student to improve"), contributions as a bullet list.
2. Related work: LLM-as-a-judge and automated short-answer grading, Indic OCR (Bodhan / AI4Bharat IndicOCR), selective prediction. Cite only papers you are sure exist; leave `% TODO cite` otherwise.
3. System: pipeline figure in TikZ (ingest, OCR, segmentation, criterion grading, advocate, critic, confidence, feedback, red ink), then one subsection per stage. Take facts from `README.md` and the code, not from `docs/archive/` (its numbers came from mock outputs and must not be reused).
4. Evaluation protocol: from `docs/evaluation.md`.
5. Results: `\input{results/agreement}`, ablation, robustness, OCR, groups; coverage, bias and ablation figures. Prose uses `\pending{}` (a macro rendering a red "[pending]") where a number will go.
6. Discussion and limitations; 7. Ethics and privacy (anonymiser, no free-tier LLM on real sheets, AI-marked stamp, defer-to-teacher); 8. Conclusion.
Appendix: an example red-ink page (placeholder image path `results/figures/example_redink.png`).

## Done when

- `make -C docs/report` builds `main.pdf` locally with a standard TeX Live, with no undefined references or citations.
- The workflow builds it in CI.
- No number in the text that is not either from `\input` tables or wrapped in `\pending{}`.
- `pytest -q` still passes (nothing in Python changes).

## Out of scope

Running experiments, writing real result numbers, slides.
