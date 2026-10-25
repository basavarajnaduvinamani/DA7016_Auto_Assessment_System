# 04: Demo hardening for Render

Status: done
Depends on: 01 (uses the `fake` provider)

## Goal

The public Gradio demo on Render's free plan must never crash or burn credits in front of a TA: it always works with the sample sheet, degrades gracefully without keys, and rejects bad uploads cleanly.

## Files

- `app.py`, `src/autoassess/demo.py`, `render.yaml`, `docs/deploy.md`.
- New `tests/test_app_guards.py` (test `demo.py` functions directly; import `app.py` only if gradio is installed, via `pytest.importorskip`).

## Behaviour

- **Health:** `GET /healthz` returns `{"ok": true, "llm": "<provider or none>", "ocr": "<provider>"}` without calling any API. Mount it on the Gradio app's FastAPI instance. `render.yaml` uses it as `healthCheckPath`.
- **No keys:** if no LLM key is configured, the "LLM grader" choice is disabled with a note, and marking uses the lexical baseline. `AUTOASSESS_DEMO_DRY_RUN=1` uses the `fake` provider from task 01 so the full red-ink path can be shown with no key.
- **Upload limits:** reject files over `AUTOASSESS_MAX_UPLOAD_MB` (default 10) and PDFs over `AUTOASSESS_MAX_PAGES` (default 8) with a `gr.Error` message, before any OCR or LLM call. Accept only `.pdf .png .jpg .jpeg .txt`.
- **Sample button:** "Try the sample sheet" marks `data/sample_exam/answer_sheets/S002.txt` with one click.
- **Errors:** any provider error (rate limit, budget guard, network) shows a short readable message and the baseline result, never a stack trace.
- **Daily cap:** the existing daily LLM cap stays; show remaining sheets for today in the UI.

## Done when

- Tests cover: health payload with and without keys (no network), oversize file and too-many-pages rejected before OCR is called (assert with a fake OCR that records calls), wrong extension rejected, budget/provider error falls back to baseline with a message, dry-run mode produces an annotated PDF.
- `docs/deploy.md` lists every env var the demo reads, with defaults.
- `pytest -q` passes.

## Out of scope

Actually deploying (needs the user's Render account). New UI features beyond the above. Changing grading.
