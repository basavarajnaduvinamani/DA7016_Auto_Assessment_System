# 12: Code quality and repository cleanup for submission

Status: in review
Depends on: none (start now; due 29 Oct)

## Why

The course grades "Code Quality and Documentation: how readable, maintainable, well-structured and well-documented is your code", from a public repository following industry practice. Today 72 of 315 public functions/classes in `src/autoassess` have docstrings, there is no linter, and the repo carries leftovers from earlier phases.

## Do

1. **Docstrings.** Every public module, class and function in `src/autoassess/` (including `web/`, `providers/`, `datasets/`) gets a docstring: one line saying what it does, then (where not obvious) Args/Returns in Google style. Describe behaviour, not history; no "week N", "task NN" or "Codex"/"Claude" mentions. Do not change behaviour.
2. **Comments.** Add a short comment wherever a non-obvious decision lives (why the advocate exists and the critic is off by default, why quotes are fuzzy-matched, why confidence combines several signals, the prompt-injection flag, the spend ledger lock). Remove stale or misleading comments.
3. **Lint and format.** Add `ruff` to the `dev` extra with a `[tool.ruff]` config in `pyproject.toml` (line length 120, rules E, F, I, B, UP; ignore E501 if needed). Fix what it reports (imports, unused variables). Add a `ruff check .` step to the existing CI workflow.
4. **Remove leftovers.** Delete `web/` (the old offline JS demo) and `tests/test_web_parity.py`; delete `docs/archive/` (interim reports with mock numbers that contradict the final report) after copying any still-cited entries from `docs/archive/references.bib` into `docs/report/references.bib` (check nothing else references the archive). Move `notebooks/indic_ocr_colab.ipynb` to `docs/notebooks/` and mention it in the README only if it still runs; otherwise delete it. Move `AGENTS.md` and `tasks/` under `docs/development/` (update links), since they document the build process, not the product.
5. **Type hints** on public function signatures in `web/` where missing.

## Done when

- A script check (add `tests/test_docstrings.py`) asserts every public module, class and function under `src/autoassess` has a docstring.
- `ruff check .` is clean and runs in CI; `pytest -q` passes.
- No behaviour changes: the grading tests and web tests pass unchanged except for moved/deleted legacy files.

## Out of scope

README rewrite (Claude is doing it), new features.
