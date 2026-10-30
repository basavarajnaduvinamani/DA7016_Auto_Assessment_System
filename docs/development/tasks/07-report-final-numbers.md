# 07: Final report with real results, and advocate-only default

Status: done
Depends on: 03, 06

## Goal

Turn the pending report into the submitted academic report (due 29 Oct 18:00), using the measured results in `docs/report/numbers.md`. Also make the configuration the study chose (advocate only, no critic) the default.

## A. Default configuration (small Python change)

The ablation in `numbers.md` shows the critic lowers agreement and pushes marks down; advocate-only was chosen on dev.
1. `src/autoassess/demo.py`: the "two-sided review" option becomes "Advocate review" and passes `advocate=reviewer, critic=None` by default. Keep the critic available as a separate, unchecked option ("Strict critic (lowers marks; off by default)") in `app.py`.
2. `app.py` ABOUT text: describe the advocate as default and the critic as optional, citing the ablation in one sentence.
3. CLI flags stay as they are (`--critic`, `--advocate` are opt-in). Update README's recommended command to `--advocate` without `--critic`.
4. Tests for the new defaults. `pytest -q` passes.

## B. Report (`docs/report/`)

Academic style, 8-10 pages plus references and appendix. Take every number from `numbers.md`; do not invent numbers or round differently. Remove every `\pending{}` that `numbers.md` now covers. A `TBD` in `numbers.md` stays `\pending{}` (Claude fills these in).

1. **Results tables.** Replace the placeholder tables in `docs/report/results/` with real tables typed from `numbers.md` (booktabs): main SPRAG test results, ablation (dev and test side by side), model comparison, handwritten set, injection check. Keep the `\input{results/...}` convention; add new files as needed. Drop tables with no data (robustness, OCR CER, groups) and their prose, or move them to a short "not measured" paragraph in limitations. Delete figure references whose figures do not exist; keep `example_redink.png` as pending.
2. **Evaluation section.** Rewrite to describe what was actually done: the two datasets, the question-level dev/test split, "all decisions on dev, test once", consensus of two graders for SPRAG, single teacher for the handwritten set, metrics (QWK half-mark bins, MAE, within-1, signed bias, bootstrap CIs clustered by question). Remove protocol text about studies that were not run (feedback-improvement study, scan-vs-transcript pairing); mention them under future work.
3. **Results section.** One subsection each: headline agreement (with human-human ceiling and baseline), ablation (the critic finding is the main analytical result: say why a critic that can only lower marks increases negative bias), confidence gating (62% auto-marked at MAE 0.66), model comparison (pre-registered 0.05 rule), handwritten classroom set (lower agreement, teacher generosity, OCR flags, bias correction), prompt injection (vulnerability, fix, limitation), Indic example (one worked example, not an evaluation).
4. **Discussion and limitations.** Typed SPRAG is not handwriting; handwritten set is small (9 students) with one grader; bias correction is a post-hoc offset; injection pattern is wording-specific; feedback quality not yet rated by students; agreement far below human-human, so the system is framed as selective auto-marking with teacher review, not a replacement.
5. **Related work.** Expand to about 600 words: automated short answer grading (Mohler et al. 2011; Burrows et al. 2015 survey), LLM-as-a-judge (Zheng et al. 2023), LLM grading of short answers, SPRAG (cite the dataset paper/Zenodo record), selective prediction / abstention (Geifman and El-Yaniv 2017), prompt injection (Greshake et al. 2023), AI4Bharat Indic models. Only cite works you can verify exist with correct authors/year; otherwise leave `% TODO cite`.
6. **Abstract and conclusion** state the headline numbers from `numbers.md`.
7. `make -C docs/report` builds with no undefined references or citations. CI builds the PDF.

## Done when

- No `\pending{}` remains except for `TBD` items and the red-ink example image.
- Every number in the PDF appears in `numbers.md`.
- `pytest -q` passes.

## Out of scope

Running experiments, changing `numbers.md` (Claude owns it), slides (task 08).
