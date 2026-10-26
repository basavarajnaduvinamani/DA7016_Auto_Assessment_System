# 11: Teacher web app, part 3: exports, class report, deploy

Status: in review
Depends on: 10

## Goal

Teachers can take results away, and anyone can run the app with one command or a public link.

## Exports (assignment page)

- **Grade sheet**: CSV and XLSX (`openpyxl`, add to the `web` extra): one row per student, a column per question, total, percentage, "reviewed by teacher" flag; overrides applied.
- **Marked sheets**: a zip of the marked PDFs, named `<roll_no>_<name>_marked.pdf`.
- **Class report** page: reuse `classwork.class_report` / `class_report_html` (averages per question, common misconceptions, inconsistent-mark pairs), with a print stylesheet.

## Deploy

- `Dockerfile` (python:3.12-slim, installs `.[web,ingest,annotate]`, runs `autoassess serve --host 0.0.0.0 --port $PORT`), `.dockerignore` excluding `data/private`, `runs`, `.cache`, `.redink`.
- `render.yaml`: start command becomes `autoassess serve --host 0.0.0.0 --port $PORT`; health check `/healthz`; note in `docs/deploy.md` that the free plan's disk resets on restart, so the demo data is re-seeded.
- `docs/deploy.md`: three ways to run (local install, Docker, Render), environment variables (keys, `AUTOASSESS_SECRET_KEY`, `AUTOASSESS_DATA_DIR`, dry run), and a 60-second demo script for the TA call (sign in, open class, open review queue, change a mark, release, download grade sheet).

## Done when

- Tests: CSV/XLSX contents with an override applied, zip names, class report renders, Docker build context excludes private data (test the `.dockerignore` patterns). `pytest -q` passes.
- `docker build` succeeds in CI (add a job that builds without pushing).

## Out of scope

Real authentication, student accounts, LMS sync.
