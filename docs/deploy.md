# Running Second Read

The teacher app and its Gradio lab run in one process. **Demo sign-in. Not for real student data.** Accounts are seeded local records without passwords; signed cookies are not real authentication. The app is for a synthetic demonstration, not public collection of student work.

## Local install

From the repository, using Python 3.11 or newer:

```bash
pip install ".[web,ingest,annotate]"
AUTOASSESS_DEMO_DRY_RUN=1 autoassess serve --host 127.0.0.1 --port 8000
```

Open http://localhost:8000, then **Sign in as demo teacher**. The SQLite file and uploads live in `AUTOASSESS_DATA_DIR` (default `.redink/`); `--data-dir DIR` overrides it. `--reset-demo` replaces local app records with the synthetic demo. Keep one server process per data directory. Two worker threads mark queued sheets; jobs interrupted while running resume at startup. The Gradio lab is at `/lab/`; `python app.py` still runs the standalone lab.

## Docker

```bash
docker build -t secondread .
docker run --rm -p 8000:8000 -e AUTOASSESS_DEMO_DRY_RUN=1 -v secondread-data:/var/lib/secondread secondread
```

Open http://localhost:8000. The Python 3.12 slim image runs as a non-root user. `PORT` defaults to 8000; if changed, map that container port. The named volume preserves SQLite, uploads and annotations. Without a volume, removing the container loses app data and the next container starts with the synthetic seed. Mount provider credentials at runtime or pass them as environment variables; never bake them into the image. `.dockerignore` excludes private datasets, run/cache directories, local app data and `.env` files. CI builds without pushing and checks startup with container networking disabled. On a network with a private TLS proxy, an optional build-only certificate can be passed with `--secret id=build_ca,src=/path/to/ca-bundle.pem`; the certificate is not copied into the image and TLS verification remains enabled.

## Render (free plan)

1. Sign in at [render.com](https://render.com) with GitHub.
2. Choose **New > Blueprint**, select this repository and branch `main`, and apply.
3. For an offline demonstration set `AUTOASSESS_DEMO_DRY_RUN=1`. To use live providers, leave it off and configure keys securely in the Environment settings. The blueprint selects OpenRouter; a Gemini key alone does not enable that selection.
4. Wait for the build and `/healthz`, then open the service URL. Free services can sleep; warm it up before the call. The `keep-warm` workflow (`.github/workflows/keep-warm.yml`) GETs `/healthz` every 10 minutes to keep one free service awake; set the repository variable `RENDER_HEALTHZ_URL` if your service URL differs from `https://secondread-grader.onrender.com`. It uses most of the workspace's free instance hours, so disable it (Actions > keep-warm > Disable) if you run a second free service, and note GitHub may delay or, after 60 days without repository activity, pause scheduled runs. These repository changes configure deployment but do not publish a service.

The blueprint installs `.[web,ingest,annotate]` and starts `autoassess serve --host 0.0.0.0 --port $PORT`. `GET /healthz` returns `{"ok": true, "llm": "<provider or none>", "ocr": "<configured provider>"}` without provider calls; this is process readiness, not connectivity. Render generates `AUTOASSESS_SECRET_KEY` and stores data at `/tmp/redink`. **The free plan’s disk resets on restart/redeploy: app records, overrides, uploads, annotations and local ledgers are lost, and the synthetic demo data is re-seeded.** Download anything needed before a restart. A fixed signing key does not persist the database.

The first start seeds ten synthetic students and a sample assignment pre-graded with the fake provider. This never uses paid startup grading. When OCR is configured, the optional S002 scan is assigned to synthetic S004 and seed-graded from its known packaged transcript, with no startup OCR calls. Live scan uploads still require working OCR. The demo extra pins Gradio to `>=6.30,<6.31`, tested with 6.30.0. Packaged samples support non-editable installs; `data/sample_exam/` remains the source of truth.

## Pilot setup

What a teacher pilot adds to the demo: sign-in by one-time email code, records and files that
survive restarts, a pilot log export and a delete-my-data button. The demo teacher button and
`AUTOASSESS_DEMO_DRY_RUN` behave exactly as before.

### Sign-in

A teacher types an email and gets a 6-digit code by email. Codes expire after 10 minutes, work
once, and die after 5 wrong tries or when a newer code is sent. Only a keyed hash is stored.
Limits: 3 codes per email per 15 minutes and 10 per day, 10 code requests per client per hour,
and 20 wrong codes per client per 15 minutes. The account is created at the first successful
sign-in, for emails on `AUTOASSESS_PILOT_EMAILS` (addresses or `@domain`, or `*` for anyone).
Everyone else sees the same "check your email" screen, but no email is sent.

Mail goes through an HTTPS API, never SMTP:
- **Resend** (`RESEND_API_KEY`): free for 3,000 emails a month, 100 a day. It sends to other
  people only from a domain you have verified (DNS records). Without one it delivers only to
  your own address.
- **Brevo** (`BREVO_API_KEY`): free for 300 emails a day. One verified sender address is enough,
  so it works without a domain (mail from a gmail.com sender may land in spam).

### Storage

With `DATABASE_URL` set, every table lives in Postgres and every uploaded sheet and marked
PDF/page is also copied into the `blobs` table. After a restart, an assignment's files come back
the first time it is opened. Measured size: about 1 MB per typed sheet (marked PDF plus pages),
more for scans (the scan and its page images), and the same again for a re-marked copy after a
change. `AUTOASSESS_S3_BUCKET` (with `pip install ".[s3]"`) moves the files to any S3-compatible bucket.

Free tiers (checked 31 Oct 2026; confirm on each pricing page):

| Service | Free limits that matter |
| --- | --- |
| Neon Postgres | 0.5 GB storage per project, 100 CU-hours compute per project per month, 5 GB network transfer per month; scales to zero after 5 minutes idle |
| Supabase | 500 MB database, 1 GB file storage, 2 active projects; paused after 1 week without activity |
| Render web service | 750 instance hours per workspace per month; sleeps after 15 minutes without traffic, about a minute to wake; disk is wiped on every restart and deploy |
| Render Postgres | 1 GB, expires 30 days after creation, no backups (not recommended for a pilot) |

At about 1 to 3 MB per sheet, Neon's 0.5 GB holds roughly 150 to 400 marked sheets. Check
usage on the Neon dashboard. A teacher's delete button frees their space at once.

### Render settings

Service > Settings:
- Build Command: `pip install ".[web,ingest,annotate,postgres]"`
- Start Command: `autoassess serve --host 0.0.0.0 --port $PORT`
- Health Check Path: `/healthz`

Service > Environment, added to the existing keys:

| Key | Value |
| --- | --- |
| `DATABASE_URL` | Neon connection string, `postgresql://...neon.tech/neondb?sslmode=require` (create the project in the region nearest the Render service) |
| `BREVO_API_KEY` or `RESEND_API_KEY` | the mail key |
| `AUTOASSESS_MAIL_FROM` | `Second Read <the verified sender>` |
| `AUTOASSESS_PILOT_EMAILS` | the pilot teachers' emails, comma separated (or `@school.edu`) |
| `AUTOASSESS_ADMIN_EMAILS` | your own email, for the all-teachers pilot log |
| `AUTOASSESS_SECRET_KEY` | a long random string, so sign-ins survive restarts |
| `AUTOASSESS_BEHIND_PROXY` | `1` |
| `AUTOASSESS_PILOT_END` | the date pilot data is deleted, e.g. `31 December 2026` |
| `AUTOASSESS_DATA_LOCATION` | e.g. `Render (Oregon, US) and Neon Postgres (AWS US West)` |

The schema is created on first start. `autoassess migrate` does it by hand, and
`autoassess migrate --from-sqlite .redink --data-dir /tmp/redink` copies a local workspace in
(`--data-dir` must match the server's `AUTOASSESS_DATA_DIR`).

### Keeping it awake

GitHub runs scheduled workflows late: the 10-minute keep-warm ran three times in eleven hours on
31 Oct 2026. For a pilot, add a free external monitor that requests
`https://secondread-grader.onrender.com/healthz` every 5 minutes (UptimeRobot's free plan, or
cron-job.org). An always-on service uses about 744 of the 750 free hours, so keep only one.

### Pilot data

- Each teacher: **Account > Download my pilot log (CSV)**. Admins also get **Download every
  teacher's log**. From a shell: `autoassess pilot-export --out pilot.csv`.
- The CSV has one row per assignment and a summary row per teacher (`level`): sheets graded and
  reviewed, review minutes, minutes per sheet, median seconds per answer, override rate,
  calibration shift (mean teacher-minus-AI mark change) and direction. Teachers appear as `T<id>`.
  There is no student text, no names, no roll numbers and no reasons.
- **Account > Delete all my data** (after typing the email) removes the teacher's account,
  classes, rosters, sheets, marks, files, logs and sign-in records at once.

## A 60-second TA demonstration

- **0–10 seconds:** sign in as the demo teacher and open **DA7016 Generative AI, Section A**.
- **10–20 seconds:** open the seeded sample assignment and its **Review answers** queue. Explain that flagged answers appear first and the queue also contains the remaining marked answers.
- **20–35 seconds:** open an answer, inspect the quote, then **Change mark** with a reason. **Save mark & accept** retains the original decision and a teacher override.
- **35–45 seconds:** return to the assignment and **Release results**. Confirm release anyway only if unresolved flags remain; ungraded uploads must finish first.
- **45–60 seconds:** download **Grade sheet · CSV** or **XLSX**, open a **Marked PDF**, and show the printable **Class report** if time allows.

Rehearse with the cached synthetic seed before the call. Exports use current overrides; ungraded roster marks stay blank. `reviewed_by_teacher` is true only for sheets with all questions accepted, so partial review is not mislabeled complete. ZIPs contain graded PDFs named `<roll_no>_<name>_marked.pdf`; unsafe path characters are replaced and rare naming collisions receive an ID suffix. PDF downloads are rebuilt without provider calls. Class-report consistency pairs are derived from current marks and answer similarity without changing accepted decisions. Real authentication, student accounts and LMS sync remain out of scope.

## A dependable demonstration

With no LLM key, both grader selectors are fixed to **Lexical baseline** and the UI explains why the LLM choice is unavailable. The **Try the sample sheet** button immediately marks the bundled `S002.txt` with the sample rubric. Typed text needs no OCR key. **Sample sheets** also includes `S002_scan.pdf` (under 300 KB), rendered from S002 using the annotator’s ruled-page layout. Choose it to populate the upload, then click **Mark it** to demonstrate OCR; it requires configured OCR and is unavailable in text-only dry-run mode. Each visitor’s last marking result is held in Gradio session state for regrades. **Advocate review** is checked by default for both individual and class marking; **Strict critic (lowers marks; off by default)** is a separate unchecked option, following the SPRAG dev ablation. Scans require a configured OCR provider; unsupported or excessive files are rejected with readable errors before OCR or LLM work. Allowed answer-sheet extensions are `.pdf`, `.png`, `.jpg`, `.jpeg` and `.txt`.

Set `AUTOASSESS_DEMO_DRY_RUN=1` to show the full scripted grading, advocate review, feedback and red-ink path without provider calls. This uses task 01's fake provider, ignores configured LLM/OCR/translation credentials for the demo and accepts typed `.txt` sheets only. It is a workflow demonstration, not semantic assessment. It does not consume the paid LLM daily allowance. Feedback stays in English. Setting the shared provider to `fake` also enables scripted text grading.

If grading, review or translation fails, the demo shows a short notice and the English lexical-baseline result, using the already-read sheet. Provider error text and stack traces are not shown. An OCR outage cannot be repaired by a lexical grader: its fallback report explicitly says no answers were extracted or assessed and asks for a typed sheet. An unconfigured scanner path instead prompts for OCR configuration. Regrade service failures preserve the original mark and direct the student to a teacher.

The UI displays remaining LLM sheets for the server's current day and refreshes after marking. The daily cap applies to single sheets and classes; a class reserves its whole sheet count or falls back as a whole. Reservations are protected against concurrent callbacks in the single server process. Failed provider attempts count conservatively, while baseline and scripted runs do not. This cap covers initial sheet marking, not regrade requests; provider spend guards still apply to live regrades.

## Environment variables and defaults

Settings are loaded from process variables and an optional local `.env` (existing process values win). Never commit a real `.env` or keys. Empty shared setting values generally use the documented default. Variables below are the app's controls and all shared settings it loads; library-specific tuning is not required.

| Variable | Application default | Meaning / blueprint override |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Standalone lab bind address; teacher app uses `--host`. |
| `PORT` | lab `7860`; container `8000` | Teacher CLI defaults to `--port 8000`; Render/container startup passes `$PORT`. |
| `AUTOASSESS_DATA_DIR` | `.redink/` | SQLite and files; CLI `--data-dir` wins. Docker `/var/lib/secondread`, Render `/tmp/redink`. |
| `AUTOASSESS_SECRET_KEY` | random per process | Signed demo-session secret. Unset values invalidate sessions after restart; Render generates one. |
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
