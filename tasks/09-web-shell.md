# 09: Teacher web app, part 1: shell, mock sign-in, classes

Status: todo
Depends on: 07, 08 (start only after both are merged)

Concept (read first): https://claude.ai/artifact/U42QKHoJ7rxqsqRfKCRrkt ("Red-Ink Grader: product concept"). Tasks 09-11 build its "Red-Ink Classroom" teacher app. The grading engine does not change.

## Goal

A professional-looking web app shell a teacher can sign in to and manage classes in, served by one process with one command. The current Gradio app keeps working at `/lab`.

## Stack (fixed; do not add others)

- FastAPI + Jinja2 templates + htmx (vendored `htmx.min.js` in `static/`, no CDN at runtime) + one hand-written CSS file. No JavaScript build step, no React.
- Storage: stdlib `sqlite3` in `src/autoassess/web/store.py`, one file at `$AUTOASSESS_DATA_DIR/redink.db` (default `./.redink/`), uploads under `$AUTOASSESS_DATA_DIR/files/`. Schema created on start; a `schema_version` table for later migrations.
- New `web` extra in `pyproject.toml`: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `itsdangerous`, plus the `demo` extra (for `/lab`). Templates and static files ship as package data.

## Files

- `src/autoassess/web/__init__.py`, `app.py` (FastAPI app factory `create_app(data_dir=None)`), `store.py`, `auth.py`, `seed.py`, `templates/`, `static/`.
- CLI: `autoassess serve [--host 0.0.0.0] [--port 8000] [--data-dir DIR] [--reset-demo]`.
- Mount the existing Gradio `demo` from `app.py` at `/lab` (`gr.mount_gradio_app`). Move the root `app.py` logic so it is importable without side effects, or import it lazily; keep `python app.py` working.
- Keep `/healthz` (same payload as today) on the new app.

## Sign-in (mocked, no real auth)

- Sign-in page with the product name, an email field and a "Continue" button, plus a one-click "Sign in as demo teacher" button.
- Accounts come from the seeded `teachers` table; unknown emails are refused with a friendly message. No passwords are stored or asked.
- Session = signed cookie (`itsdangerous`, secret from `AUTOASSESS_SECRET_KEY`, random per process if unset), `HttpOnly`, `SameSite=Lax`. Sign-out clears it. Every page except sign-in, `/healthz` and static requires a session; redirect to sign-in otherwise.
- State the mock clearly in the footer: "Demo sign-in. Not for real student data."

## Screens

1. **Dashboard** (`/`): greeting with the teacher's name; class cards (name, subject, students, assignments, "N answers need review"); "New class" button.
2. **Class** (`/classes/{id}`): roster table (roll no, name), "Import roster (CSV: roll_no,name)", "Add student"; assignment list (empty state text for now: "Assignments arrive in the next release").
3. **New class** form: name, subject, section.
Header on every page: product name, class breadcrumb, teacher name, sign out. Layout works at 1280 px and 390 px wide.

## Seed

On start, if the database is empty (or with `--reset-demo`): teacher "Demo Teacher" (demo@redink.local), class "DA7016 Generative AI, Section A" with 10 students S001-S010 (synthetic names). Idempotent.

## Done when

- `pip install ".[web]" && autoassess serve` shows the sign-in page at http://localhost:8000; demo sign-in reaches the dashboard; creating a class and importing a roster CSV work; `/lab` shows the Gradio app; `/healthz` returns 200.
- Tests with FastAPI's TestClient: unauthenticated redirect, demo sign-in, unknown email refused, class create, roster import (good and malformed CSV), seed idempotent, `/lab` and `/healthz` respond. `pytest -q` passes.
- README gets a "Teacher app" section with the two commands.

## Out of scope

Assignments, uploads, grading (task 10); export and deploy (task 11); real authentication; student accounts.
