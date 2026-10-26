# Deploying the demo on Render (free)

`app.py` mounts Gradio on a FastAPI app and serves it with Uvicorn. The Render blueprint installs `.[ingest,api,demo]`, starts `python app.py`, and checks `GET /healthz`. Health returns `{"ok": true, "llm": "<provider or none>", "ocr": "<configured provider>"}` without constructing providers, checking credits or making API calls. It indicates process readiness, not provider connectivity.

1. Sign in at [render.com](https://render.com) with GitHub.
2. Choose **New > Blueprint**, select this repository and branch `main`, and apply.
3. Configure provider keys securely in the service's Environment settings if live grading is needed. The blueprint selects OpenRouter; a Gemini key alone does not enable that selection.
4. Wait for Render's build and health check, then open the service URL. No deployment is performed by this repository task.

The demo extra pins Gradio to `>=6.30,<6.31`, tested with 6.30.0. Sample exam files ship inside the Python package, so a non-editable `pip install .` also supports the default rubric and examples. `data/sample_exam/` remains the source of truth; tests check that the packaged copy matches.

## A dependable demonstration

With no LLM key, both grader selectors are fixed to **Lexical baseline** and the UI explains why the LLM choice is unavailable. The **Try the sample sheet** button immediately marks the bundled `S002.txt` with the sample rubric. Typed text needs no OCR key. **Sample sheets** also includes `S002_scan.pdf` (under 300 KB), rendered from S002 using the annotator’s ruled-page layout. Choose it to populate the upload, then click **Mark it** to demonstrate OCR; it requires configured OCR and is unavailable in text-only dry-run mode. Each visitor’s last marking result is held in Gradio session state for regrades. **Advocate review** is checked by default for both individual and class marking; **Strict critic (lowers marks; off by default)** is a separate unchecked option, following the SPRAG dev ablation. Scans require a configured OCR provider; unsupported or excessive files are rejected with readable errors before OCR or LLM work. Allowed answer-sheet extensions are `.pdf`, `.png`, `.jpg`, `.jpeg` and `.txt`.

Set `AUTOASSESS_DEMO_DRY_RUN=1` to show the full scripted grading, advocate review, feedback and red-ink path without provider calls. This uses task 01's fake provider, ignores configured LLM/OCR/translation credentials for the demo and accepts typed `.txt` sheets only. It is a workflow demonstration, not semantic assessment. It does not consume the paid LLM daily allowance. Feedback stays in English. Setting the shared provider to `fake` also enables scripted text grading.

If grading, review or translation fails, the demo shows a short notice and the English lexical-baseline result, using the already-read sheet. Provider error text and stack traces are not shown. An OCR outage cannot be repaired by a lexical grader: its fallback report explicitly says no answers were extracted or assessed and asks for a typed sheet. An unconfigured scanner path instead prompts for OCR configuration. Regrade service failures preserve the original mark and direct the student to a teacher.

The UI displays remaining LLM sheets for the server's current day and refreshes after marking. The daily cap applies to single sheets and classes; a class reserves its whole sheet count or falls back as a whole. Reservations are protected against concurrent callbacks in the single server process. Failed provider attempts count conservatively, while baseline and scripted runs do not. This cap covers initial sheet marking, not regrade requests; provider spend guards still apply to live regrades.

## Environment variables and defaults

Settings are loaded from process variables and an optional local `.env` (existing process values win). Never commit a real `.env` or keys. Empty shared setting values generally use the documented default. Variables below are the app's controls and all shared settings it loads; library-specific tuning is not required.

| Variable | Application default | Meaning / blueprint override |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Uvicorn bind address. |
| `PORT` | `7860` | Uvicorn port; Render supplies its listening port. |
| `AUTOASSESS_DEMO_DRY_RUN` | unset / off | Exactly `1` selects the offline scripted text mode; blueprint `0`. |
| `AUTOASSESS_MAX_UPLOAD_MB` | `10` | Maximum bytes per uploaded file in MiB, enforced by Gradio and sheet validation. |
| `AUTOASSESS_MAX_PAGES` | `8` | Maximum PDF answer-sheet pages, inspected before OCR; encrypted or unreadable PDFs are rejected. |
| `AUTOASSESS_DEMO_DAILY_SHEETS` | `40` | Daily allowance for live LLM sheet attempts, shared across visitors. |
| `AUTOASSESS_CACHE_DIR` | `.cache` | Provider ledgers, caches, daily counter and regrade log; blueprint `/tmp/autoassess-cache`. |
| `AUTOASSESS_LLM_PROVIDER` | auto-select | First configured Gemini key, then OpenRouter; otherwise Gemini. Explicit choices: `gemini`, `openrouter`, `custom`, `fake`. Blueprint `openrouter`. |
| `GEMINI_API_KEY` | empty | Gemini credential, with shared LLM key fallback. |
| `OPENROUTER_API_KEY` | empty | OpenRouter credential. |
| `AUTOASSESS_LLM_API_KEY` | empty | Custom endpoint key, also the fallback Gemini key. Gemini and OpenRouter without a key are disabled in this demo; a `custom` endpoint (for example local Ollama) works without one. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Default Gemini model. |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | Default OpenRouter model, also used in the blueprint. |
| `AUTOASSESS_LLM_MODEL` | provider default | Overrides the model except in fake mode; empty for custom providers unless configured. |
| `AUTOASSESS_LLM_BASE_URL` | `http://localhost:11434/v1` for custom | Custom OpenAI-compatible endpoint; a nonempty value selects custom when no provider is explicitly selected. Built-in providers use their fixed endpoints. |
| `AUTOASSESS_CRITIC_MODEL` | grading model | Optional reviewer model used for the critic and advocate. |
| `AUTOASSESS_SECOND_MODEL` | empty | Shared setting loaded by Settings; the current demo does not request a second examiner. |
| `OPENROUTER_BUDGET_USD` | `18` | OpenRouter spend guard; blueprint uses the same value. |
| `AUTOASSESS_OCR_PROVIDER` | `text` | `text`, `indic-local`, `indic-precomputed`, `vision` or `bodhan`. For a scan with `text`, the demo chooses Bodhan if a key exists, then vision if a model is set. Health reports the configured provider. |
| `AUTOASSESS_OCR_JSON_DIR` | `ocr_json` | Precomputed OCR JSON directory. |
| `AUTOASSESS_INDIC_OCR_REPO` | empty | Local IndicOCR snapshot; otherwise the local provider downloads weights. Local GPU/weights are not prepared by the free Render blueprint. |
| `AUTOASSESS_VISION_MODEL` | empty | Model for vision transcription of scans, using the selected LLM endpoint/key. |
| `AUTOASSESS_BLANK_INK` | `0.0005` | Ink-share threshold for skipping blank scanned pages. Tune cautiously for faint writing. |
| `BODHAN_API_KEY` | empty | Shared OCR/translation credential. |
| `BODHAN_OCR_API_KEY` | shared Bodhan key | Optional separate OCR credential. |
| `BODHAN_TRANSLATE_API_KEY` | shared Bodhan key | Optional separate translation credential. |
| `BODHAN_BASE_URL` | `https://api.bodhan.ai` | Hosted OCR and translation endpoint. |
| `BODHAN_BUDGET_INR` | `100` | Bodhan spend guard; blueprint uses the same value. |
| `AUTOASSESS_REAL_SHEETS` | off | `1`, `true` or `yes` enables the check against the known free Gemini endpoint for real sheets. |
| `AUTOASSESS_GEMINI_PAID` | off | `1`, `true` or `yes` declares a billed Gemini project; use only when the key actually has that status. |
| `PYTHON_VERSION` | Render setting | Blueprint pins `3.11.9`; the application does not read this variable. |

Gradio analytics are disabled by the app. Its optional `GRADIO_TEMP_DIR` controls uploaded/downloaded temporary files (otherwise the library uses an OS temporary location). Do not make temporary upload storage public outside Gradio's intended file routes.

## Costs and privacy

Render's free service may sleep when idle and need time to wake. Open it before a demonstration. Provider prices and availability can change; confirm them with the provider rather than treating a cached dry run as a cost estimate. Baseline and scripted marking of typed sheets use no paid services. OCR and translated feedback can incur separate charges outside scripted mode.

The spend guards' ledgers and daily counter live in the cache directory. Render's ephemeral `/tmp` is cleared on restart, so these are per-instance controls rather than durable account-wide limits. Keep provider-side limits and monitor the account dashboard. A single Uvicorn worker is used; the in-process reservation lock is not a distributed quota service.

For real sheets, use consented material, remove identifiers from both text and scans, and set `AUTOASSESS_REAL_SHEETS=1`. A free-tier Gemini key may use prompts for training; use an appropriate paid provider. A flag is not a substitute for verifying provider policy. Cached answers, uploaded pages and regrade logs can contain private information even when ignored by Git. Keep the AI-marked disclosure and teacher review/appeal process visible.
