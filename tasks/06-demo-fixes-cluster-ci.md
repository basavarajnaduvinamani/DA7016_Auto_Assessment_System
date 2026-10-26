# 06: Demo fixes and question-clustered confidence intervals

Status: in review

## Goal

Two independent fixes before the 29 Oct submission: (A) bugs that would break the live TA demo; (B) bootstrap CIs that resample whole questions, so the reported intervals aren't too narrow.

## A. Demo fixes (`app.py`, `src/autoassess/demo.py`, `pyproject.toml`)

1. **Sample paths on a non-editable install.** `demo.py` sets `ROOT = Path(__file__).resolve().parents[2]`. With `pip install .` (Render) that points into site-packages, so `SAMPLE` doesn't exist. As a result, "Try the sample sheet", `gr.Examples` and the default spec all fail. Fix: ship the sample exam as package data (`src/autoassess/sample_exam/`, keeping `data/sample_exam/` as the source of truth via a test that both copies match). Alternatively, resolve `AUTOASSESS_SAMPLE_DIR`, then the repo path, then package data. Pick one and test it with a non-editable install in a temp venv, or by monkeypatching `__file__`.
2. **Per-visitor state.** `STATE["last"]` is a module global, so one visitor's regrade can hit another visitor's sheet. Use `gr.State` for the last result.
3. **Regrade crash.** `do_regrade` crashes on `choice is None` and on a missing segment, outside the try block. Both should give a friendly `gr.Error`.
4. **Pin Gradio** to the version you test with, for example `gradio>=4.40,<5` (or the version installed, as a range), in the `demo` extra.
5. **A scanned sample.** Render `data/sample_exam/answer_sheets/S002.txt` to a ruled-page PDF using the annotator's existing typed-sheet layout, as `S002_scan.pdf`. Add it to `gr.Examples`, so the PDF path can be shown with one click. Keep the file under 300 KB.

Tests: one per item where possible (the gradio import may be skipped as before; test the `demo.py` functions directly).

## B. Question-clustered bootstrap (`src/autoassess/metrics.py`, `evaluate.py`)

`bootstrap_ci` resamples single items. SPRAG has 5 answers per question, so items within a question are correlated and the CI is too narrow. Add an optional `groups: Sequence[str] | None` argument: when it is given, resample **groups** with replacement and take all items of each drawn group. `evaluate` passes the question id per item for `vs_consensus` and per-group results. The default stays item-level when groups are absent. Add `"ci_method": "cluster:question"` or `"item"` to the output.

Tests: on synthetic data where items in a group are identical, the cluster CI is wider than the item CI. Existing results stay the same when `groups=None`.

## Done when

All items above have tests, `pytest -q` passes, and README / docs/deploy.md mention the pinned Gradio and the scanned sample.

## Out of scope

New features, UI redesign, changing grading.
