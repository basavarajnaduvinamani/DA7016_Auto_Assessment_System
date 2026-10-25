# 02: Results pack: tables and figures for the report

Status: in review

## Goal

One command turns the JSON outputs of `evaluate`, `experiment ablation`, `experiment robustness` and `ocr-eval` into report-ready Markdown tables, LaTeX tables and PNG figures, so the final report never has hand-copied numbers.

## Files

- New `src/autoassess/results.py`.
- `src/autoassess/cli.py`: new subcommand `results`.
- `pyproject.toml`: new optional extra `report = ["matplotlib>=3.8"]`, imported lazily inside the figure functions only.
- New `tests/test_results.py` and small JSON fixtures under `tests/fixtures/results/` (build them by running the real functions in `evaluate.py` / `experiments.py` on fake data, or copy their exact output shapes; read those modules first).
- `docs/evaluation.md`: a short "7. Results pack" section.

## Interface

```bash
autoassess results --agreement runs/full/agreement.json \
    [--ablation runs/ablation/ablation.json] [--robustness runs/robustness/robustness.json] \
    [--ocr runs/ocr_bodhan.json ...] --out runs/results
```

Every input except `--agreement` is optional; skip sections whose input is missing. Writes into `--out`:

- `results.md`: all tables in Markdown with one-line captions.
- `tables/*.tex`: one `booktabs` table per section (`agreement.tex`, `ablation.tex`, `robustness.tex`, `ocr.tex`, `groups.tex` when per-group results exist), plain `tabular` inside, no float wrapper, so the report can `\input` them.
- `figures/coverage.png`: accuracy vs share auto-accepted (coverage curve), from the agreement JSON.
- `figures/bias.png`: signed bias per question with bootstrap CI error bars, if present.
- `figures/ablation.png`: QWK per ablation arm with the human-human line, if ablation given.
- `summary.json`: the headline numbers (system QWK, human-human QWK, MAE, within-1-mark share, signed bias, coverage at threshold 0.8, robustness pass rate) in one flat dict.

Numbers are rounded to 3 decimals in tables; CIs are shown as `0.712 [0.65, 0.77]`.

## Done when

- Tests build the pack from the fixtures and check: every file above exists (figures only when matplotlib is installed; skip those asserts with `pytest.importorskip("matplotlib")`), `summary.json` values equal the fixture values, the `.tex` files contain `\toprule` and compile-safe escaping (`%`, `_`, `&` escaped).
- Missing optional inputs produce no file for that section and no error.
- Without matplotlib, the command still writes tables and `summary.json` and prints one line saying figures were skipped.
- `pytest -q` passes. CI does not need matplotlib.

## Out of scope

Changing how metrics are computed. Running any experiment. The report itself (task 03).
