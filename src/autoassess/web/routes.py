"""Teacher assignment, upload and review routes; grading stays in the engine."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from autoassess.demo import LANGUAGES, demo_settings, llm_available, validate_upload
from autoassess.providers import make_llm
from autoassess.regrade import regrade
from autoassess.schemas import ExamSpec, SheetGrade
from autoassess.spec_builder import draft_spec, lint_spec, load_spec
from autoassess.web.forms import build_spec, question_values
from autoassess.web.grading import match_student, rebuild_artifacts
from autoassess.web.jobs import Jobs
from autoassess.web.marked import marked_page, marked_pngs
from autoassess.web.presentation import language_code
from autoassess.web.teacher_time import teacher_time

if TYPE_CHECKING:
    from autoassess.web.store import Store


def mount_assignment_routes(app: FastAPI, store: Store, templates: Jinja2Templates, jobs: Jobs) -> None:
    """Register rubric authoring, upload, job and teacher-review endpoints."""

    def render(request: Request, name: str, *, status: int = 200, **context: Any) -> Response:
        """Render a teacher template with provider availability and response status."""
        return templates.TemplateResponse(
            request=request,
            name=name,
            status_code=status,
            context={
                "teacher": request.state.teacher,
                "ai_available": llm_available(demo_settings()),
                "languages": LANGUAGES,
                **context,
            },
        )

    def classroom(request: Request, class_id: int) -> dict[str, Any]:
        """Find a class owned by the current teacher or return 404."""
        row = store.classroom(class_id, request.state.teacher["id"])
        if row is None:
            raise HTTPException(404, "Class not found")
        return row

    def assignment(request: Request, assignment_id: int) -> dict[str, Any]:
        """Find an assignment owned by the current teacher or return 404."""
        row = store.assignment(assignment_id, request.state.teacher["id"])
        if row is None:
            raise HTTPException(404, "Assignment not found")
        return row

    def submission(request: Request, assignment_id: int, submission_id: int) -> dict[str, Any]:
        """Find an uploaded sheet within an owned assignment or return 404."""
        assignment(request, assignment_id)
        row = store.submission(submission_id)
        if row is None or row["assignment_id"] != assignment_id:
            raise HTTPException(404, "Sheet not found")
        return row

    def page_context(request: Request, assignment_id: int) -> dict[str, Any]:
        """Collect the rubric, progress and class context for an assignment page."""
        row = assignment(request, assignment_id)
        spec = ExamSpec.model_validate_json(row["spec_json"])
        return {
            "assignment": row,
            "classroom": classroom(request, row["class_id"]),
            "spec": spec,
            "summary": store.assignment_summary(assignment_id),
            "submissions": store.submissions(assignment_id),
            "warnings": lint_spec(spec),
            "teacher_time": teacher_time(store, assignment_id),
            "translation_notice": row["feedback_language"] != "English" and not demo_settings().translate_key,
            "sheet_notices": [
                {"name": sub["original_name"], "note": note}
                for sub in store.submissions(assignment_id)
                if sub["run_json"]
                for note in json.loads(sub["run_json"]).get("notes", [])
                if note.startswith("No recognisable questions")
            ],
        }

    def assignment_page(
        request: Request, assignment_id: int, *, error: str | None = None, message: str | None = None, status: int = 200
    ) -> Response:
        """Render an assignment with optional validation or completion notices."""
        return render(
            request,
            "assignment.html",
            status=status,
            **page_context(request, assignment_id),
            error=error,
            message=message,
        )

    @app.get("/classes/{class_id}/assignments/new")
    def new_assignment(request: Request, class_id: int) -> Response:
        """Show a blank question builder for an owned class."""
        return render(
            request,
            "new_assignment.html",
            classroom=classroom(request, class_id),
            questions=[
                {
                    "index": 1,
                    "text": "",
                    "max_marks": "",
                    "model_answer": "",
                    "criteria": [{"description": "", "marks": ""}],
                }
            ],
        )

    @app.post("/classes/{class_id}/assignments")
    async def save_assignment(request: Request, class_id: int) -> Response:
        """Validate a form or imported rubric and create an assignment."""
        room = classroom(request, class_id)
        form = await request.form()
        title = str(form.get("title", "")).strip()
        values = []
        feedback_language = str(form.get("feedback_language", "English"))
        try:
            count = int(form.get("question_count", 1))
            if not 1 <= count <= 50:
                raise ValueError("Use between 1 and 50 questions.")
            values = [question_values(form, i) for i in range(1, count + 1)]
            imported = form.get("rubric")
            if imported and getattr(imported, "filename", ""):
                suffix = Path(imported.filename).suffix.lower()
                content = await imported.read(1024 * 1024 + 1)
                if suffix not in (".yaml", ".yml", ".json") or len(content) > 1024 * 1024:
                    raise ValueError("Import a YAML/JSON rubric under 1 MB.")
                path = store.root / "files" / f"rubric-{uuid.uuid4().hex}{suffix}"
                try:
                    path.write_bytes(content)
                    spec = load_spec(path)
                finally:
                    path.unlink(missing_ok=True)
                title = title or spec.title
            else:
                spec = build_spec(title, values)
            lint_spec(spec)
            assignment_id = store.create_assignment(class_id, title, spec, feedback_language=feedback_language)
        except (ValueError, ValidationError, TypeError, KeyError) as err:
            details = (
                "; ".join(
                    item["msg"].removeprefix("Value error, ")
                    for item in err.errors(include_url=False, include_input=False)
                )
                if isinstance(err, ValidationError)
                else str(err)
            )
            return render(
                request,
                "new_assignment.html",
                status=400,
                classroom=room,
                questions=values
                or [
                    {
                        "index": 1,
                        "text": "",
                        "max_marks": "",
                        "model_answer": "",
                        "criteria": [{"description": "", "marks": ""}],
                    }
                ],
                values={"title": title, "feedback_language": feedback_language},
                error=f"Check the rubric: {details[:1200]}",
            )
        except Exception:
            return render(
                request,
                "new_assignment.html",
                status=400,
                classroom=room,
                questions=values,
                values={"title": title, "feedback_language": feedback_language},
                error="The rubric could not be read. Check its YAML/JSON format.",
            )
        return RedirectResponse(f"/assignments/{assignment_id}", status_code=303)

    @app.post("/classes/{class_id}/assignments/suggest")
    async def suggest(request: Request, class_id: int, index: int = 1) -> Response:
        """Draft criterion suggestions without replacing the teacher's saved rubric."""
        room = classroom(request, class_id)
        if not 1 <= index <= 50:
            raise HTTPException(400, "Invalid question")
        form = await request.form()
        try:
            value = question_values(form, index)
        except ValueError:
            raise HTTPException(400, "Each criterion needs a description and marks.") from None
        settings = demo_settings()
        error = None
        if not llm_available(settings):
            error = "Criteria suggestions need an available LLM. You can write the rubric yourself."
        else:
            try:
                marks = float(value["max_marks"])
                if not value["text"].strip() or not marks > 0:
                    raise ValueError("Add the question and its maximum marks before requesting suggestions.")
                spec = await run_in_threadpool(
                    draft_spec,
                    f"Q1 ({marks:g} marks): {value['text']}",
                    f"Suggest checkable criteria totalling {marks:g} marks for the question and reference answer. The teacher will review them.",
                    value["model_answer"],
                    make_llm(settings),
                )
                proposed = spec.questions[0]
                value["criteria"] = [{"description": c.description, "marks": c.marks} for c in proposed.criteria]
            except Exception:
                error = "Suggestions are unavailable. Keep your current rubric or try again later."
        return render(request, "question_form.html", q=value, classroom=room, suggestion_error=error)

    @app.get("/assignments/{assignment_id}")
    def show_assignment(request: Request, assignment_id: int) -> Response:
        """Display current assignment progress and review actions."""
        return assignment_page(request, assignment_id)

    @app.get("/assignments/{assignment_id}/progress")
    def progress(request: Request, assignment_id: int) -> Response:
        """Refresh active job progress and release controls as an htmx fragment."""
        assignment(request, assignment_id)
        jobs.kick()
        return render(request, "progress.html", **page_context(request, assignment_id))

    def upload_page(request: Request, assignment_id: int, **kwargs: Any) -> Response:
        """Render uploaded sheets and the class's matching choices."""
        context = page_context(request, assignment_id)
        return render(
            request, "upload.html", **context, students=store.students(context["assignment"]["class_id"]), **kwargs
        )

    @app.get("/assignments/{assignment_id}/upload")
    def show_upload(request: Request, assignment_id: int) -> Response:
        """Display the multi-sheet upload and student-matching page."""
        return upload_page(request, assignment_id)

    @app.post("/assignments/{assignment_id}/upload")
    async def upload(request: Request, assignment_id: int) -> Response:
        """Validate and stage a bounded batch of sheets before registering any file."""
        row = assignment(request, assignment_id)
        form = await request.form()
        incoming = [f for f in form.getlist("sheets") if getattr(f, "filename", "")]
        if not incoming:
            return upload_page(request, assignment_id, status=400, error="Choose at least one answer sheet to upload.")
        if row["released"] or len(incoming) > 100:
            return upload_page(
                request, assignment_id, status=400, error="Choose up to 100 sheets for an unreleased assignment."
            )
        folder = store.root / "files" / str(assignment_id) / f"upload-{uuid.uuid4().hex}"
        folder.mkdir(parents=True)
        records = []
        roster = store.students(row["class_id"])
        occupied = {s["student_id"] for s in store.submissions(assignment_id) if s["student_id"]}
        try:
            limit = int(float(os.getenv("AUTOASSESS_MAX_UPLOAD_MB", "10")) * 1024 * 1024)
            for incoming_file in incoming:
                name = Path(incoming_file.filename.replace("\\", "/")).name
                path = folder / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
                content = await incoming_file.read(limit + 1)
                if not content:
                    raise ValueError("This sheet is empty. Upload a file containing an answer.")
                path.write_bytes(content)
                validate_upload(path)
                student_id = match_student(name, roster)
                if student_id in occupied:
                    student_id = None
                if student_id:
                    occupied.add(student_id)
                records.append((student_id, name, path))
            store.add_submissions(assignment_id, records)
        except ValueError as err:
            shutil.rmtree(folder, ignore_errors=True)
            return upload_page(request, assignment_id, status=400, error=f"No files were added. {err}")
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            return upload_page(
                request,
                assignment_id,
                status=400,
                error="No files were added. Use supported sheets within the size/page limits; check that PDFs are valid and unencrypted.",
            )
        return RedirectResponse(f"/assignments/{assignment_id}/upload", status_code=303)

    @app.post("/assignments/{assignment_id}/submissions/{submission_id}/match")
    def match(request: Request, assignment_id: int, submission_id: int, student_id: int = Form(...)) -> Response:
        """Save a manual student match for an ungraded upload."""
        submission(request, assignment_id, submission_id)
        try:
            store.match_submission(submission_id, student_id)
        except (ValueError, sqlite3.IntegrityError):
            return upload_page(
                request,
                assignment_id,
                status=400,
                error="Choose an unused student in this class for an ungraded sheet.",
            )
        return RedirectResponse(f"/assignments/{assignment_id}/upload", status_code=303)

    @app.post("/assignments/{assignment_id}/grade")
    def grade_all(request: Request, assignment_id: int) -> Response:
        """Queue matched sheets and start available local workers."""
        assignment(request, assignment_id)
        if any(s["student_id"] is None for s in store.submissions(assignment_id)):
            return assignment_page(
                request, assignment_id, error="Match every uploaded sheet to a student before grading.", status=400
            )
        try:
            store.queue_assignment(assignment_id)
            jobs.kick()
        except ValueError as err:
            return assignment_page(request, assignment_id, error=str(err), status=400)
        return RedirectResponse(f"/assignments/{assignment_id}", status_code=303)

    @app.post("/assignments/{assignment_id}/submissions/{submission_id}/retry")
    def retry(request: Request, assignment_id: int, submission_id: int) -> Response:
        """Schedule another attempt for a failed sheet in an owned assignment."""
        submission(request, assignment_id, submission_id)
        row = next(s for s in store.submissions(assignment_id) if s["id"] == submission_id)
        try:
            store.retry_job(row["job_id"])
            jobs.kick()
        except ValueError as err:
            return assignment_page(request, assignment_id, status=400, error=str(err))
        return RedirectResponse(f"/assignments/{assignment_id}", status_code=303)

    @app.get("/assignments/{assignment_id}/review")
    def review(request: Request, assignment_id: int, show: str = "all") -> Response:
        """Display readable review flags with an optional flagged or injection filter."""
        context = page_context(request, assignment_id)
        rows = store.review_rows(assignment_id)
        if show == "flagged":
            rows = [row for row in rows if row["needs_review"] or row["question"].flags]
        elif show == "injection":
            rows = [row for row in rows if "possible_prompt_injection" in row["question"].flags]
        elif show != "all":
            return render(
                request,
                "review.html",
                status=400,
                **context,
                rows=[],
                show="all",
                error="Choose all, flagged or injection.",
            )
        return render(request, "review.html", **context, rows=rows, show=show)

    def answer_page(request: Request, assignment_id: int, submission_id: int, qid: str, **kwargs: Any) -> Response:
        """Render one answer, its evidence and the complete criterion decision history."""
        row = submission(request, assignment_id, submission_id)
        grade = store.effective_grade(row)
        qg = next((q for q in grade.questions if q.question_id == qid), None) if grade else None
        if qg is None:
            raise HTTPException(404, "Marked answer not found")
        context = page_context(request, assignment_id)
        saved = json.loads(row["run_json"])
        changes = store.changes(submission_id)
        rows = store.review_rows(assignment_id)
        index = next(
            i for i, r in enumerate(rows) if r["submission"]["id"] == submission_id and r["question"].question_id == qid
        )

        def link(position: int) -> str | None:
            """Build the adjacent answer URL when the requested queue position exists."""
            if not 0 <= position < len(rows):
                return None
            target = rows[position]
            return f"/assignments/{assignment_id}/review/{target['submission']['id']}/{target['question'].question_id}"

        return render(
            request,
            "answer.html",
            **context,
            submission=row,
            question=qg,
            answer_lang=language_code(context["spec"].language),
            feedback_lang=language_code(context["assignment"]["feedback_language"]) if qg.feedback_en else "en",
            rubric=context["spec"].question(qid),
            answer=saved["segments"].get(qid, {}).get("text", ""),
            image=next(
                (
                    i
                    for i, p in enumerate(saved["pages"])
                    if Path(p.get("image_path") or "").suffix.lower()
                    in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")
                ),
                None,
            ),
            marked=marked_page(
                row,
                store.root,
                qg,
                next(
                    (q for q in SheetGrade.model_validate_json(row["grade_json"]).questions if q.question_id == qid),
                    None,
                ),
            ),
            changes=[c for c in changes if c["question_id"] == qid],
            notes=saved.get("notes", []),
            version=changes[-1]["id"] if changes else 0,
            accepted=qid in store.accepted_questions(submission_id),
            previous=link(index - 1),
            next=link(index + 1),
            **kwargs,
        )

    @app.get("/assignments/{assignment_id}/review/{submission_id}/{qid}")
    def answer(request: Request, assignment_id: int, submission_id: int, qid: str) -> Response:
        """Open a marked answer belonging to an owned assignment."""
        return answer_page(request, assignment_id, submission_id, qid)

    @app.post("/assignments/{assignment_id}/review/{submission_id}/{qid}/accept")
    def accept(request: Request, assignment_id: int, submission_id: int, qid: str) -> Response:
        """Record teacher acceptance and return to the review queue."""
        submission(request, assignment_id, submission_id)
        try:
            store.accept_question(submission_id, qid, request.state.teacher["id"])
        except ValueError as err:
            raise HTTPException(400, str(err)) from err
        return RedirectResponse(f"/assignments/{assignment_id}/review", status_code=303)

    @app.post("/assignments/{assignment_id}/review/{submission_id}/{qid}/override")
    def override(
        request: Request,
        assignment_id: int,
        submission_id: int,
        qid: str,
        criterion_id: str = Form(...),
        marks: float = Form(...),
        reason: str = Form(""),
        version: int = Form(0),
    ) -> Response:
        """Save a reasoned teacher mark while retaining both criterion versions."""
        submission(request, assignment_id, submission_id)
        try:
            store.add_override(
                submission_id, qid, criterion_id, marks, reason, request.state.teacher["id"], expected_version=version
            )
        except (ValueError, KeyError) as err:
            return answer_page(request, assignment_id, submission_id, qid, status=400, error=str(err))
        return answer_page(
            request,
            assignment_id,
            submission_id,
            qid,
            message="Teacher mark saved and answer accepted. The original AI mark is kept; release again to share updated marks.",
        )

    @app.post("/assignments/{assignment_id}/review/{submission_id}/{qid}/recheck")
    def recheck(
        request: Request,
        assignment_id: int,
        submission_id: int,
        qid: str,
        criterion_id: str = Form(...),
        reason: str = Form(""),
        version: int = Form(0),
    ) -> Response:
        """Request an evidence-checked AI review and append its decision record."""
        row = submission(request, assignment_id, submission_id)
        settings = demo_settings()
        if not reason.strip() or len(reason) > 2000 or not llm_available(settings):
            return answer_page(
                request,
                assignment_id,
                submission_id,
                qid,
                status=400,
                error="Give a reason and configure an available LLM before requesting a re-check.",
            )
        changes = store.changes(submission_id)
        if version != (changes[-1]["id"] if changes else 0):
            return answer_page(
                request,
                assignment_id,
                submission_id,
                qid,
                status=400,
                error="This sheet changed in another tab. Reload before requesting a re-check.",
            )
        spec = ExamSpec.model_validate_json(assignment(request, assignment_id)["spec_json"])
        if not row["grade_json"] or not row["run_json"]:
            raise HTTPException(400, "Mark this sheet first.")
        if not any(q.id == qid and any(c.id == criterion_id for c in q.criteria) for q in spec.questions):
            raise HTTPException(400, "Choose a criterion in this assignment.")
        saved = json.loads(row["run_json"])
        try:
            new, record = regrade(
                spec,
                store.effective_grade(row),
                saved["segments"][qid]["text"],
                qid,
                criterion_id,
                reason,
                make_llm(settings),
            )
            result = next(
                c for q in new.questions if q.question_id == qid for c in q.criteria if c.criterion_id == criterion_id
            )
            store.add_override(
                submission_id,
                qid,
                criterion_id,
                result.marks_awarded,
                reason,
                request.state.teacher["id"],
                expected_version=version,
                ai_result=result,
                record=record,
            )
        except ValueError:
            return answer_page(
                request,
                assignment_id,
                submission_id,
                qid,
                status=400,
                error="The sheet changed or the re-check was invalid. Reload before trying again.",
            )
        except Exception:
            return answer_page(
                request,
                assignment_id,
                submission_id,
                qid,
                status=502,
                error="AI re-check unavailable. Your current mark is unchanged; review it manually or try later.",
            )
        return answer_page(
            request,
            assignment_id,
            submission_id,
            qid,
            message=f"AI re-check: {record.old_marks:g} → {record.new_marks:g}. Review the evidence, then accept the answer.",
        )

    @app.post("/assignments/{assignment_id}/release")
    def release(request: Request, assignment_id: int, confirm: bool = Form(False)) -> Response:
        """Rebuild current marked PDFs and release completed results."""
        assignment(request, assignment_id)
        summary = store.assignment_summary(assignment_id)
        if summary["pending"] or not summary["uploaded"] or (summary["needs_review"] and not confirm):
            return assignment_page(
                request,
                assignment_id,
                status=400,
                error="Finish grading and review flagged answers, or confirm releasing the graded answers anyway.",
            )
        try:
            for row in store.submissions(assignment_id):
                rebuild_artifacts(store, row["id"])
            store.release_assignment(assignment_id, confirm=confirm)
        except Exception:
            return assignment_page(
                request,
                assignment_id,
                status=500,
                error="The marked PDFs could not be prepared. Nothing was released; try again.",
            )
        return RedirectResponse(f"/assignments/{assignment_id}", status_code=303)

    @app.get("/assignments/{assignment_id}/submissions/{submission_id}/artifact/{kind}")
    def artifact(request: Request, assignment_id: int, submission_id: int, kind: str, index: int = 0) -> Response:
        """Serve a stored report or real page image from an owned sheet."""
        row = submission(request, assignment_id, submission_id)
        if not row["grade_json"] or index < 0:
            raise HTTPException(404, "Artifact not found")
        saved = json.loads(row["run_json"])
        artifacts = json.loads(row["artifacts_json"])
        if kind == "page":
            path = saved["pages"][index].get("image_path") if index < len(saved["pages"]) else None
            if Path(path or "").suffix.lower() not in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
                path = None
        elif kind == "marked":
            pngs = marked_pngs(row, store.root)
            path = str(pngs[index]) if index < len(pngs) else None
        elif kind == "pdf":
            path = artifacts.get("pdf")
        elif kind == "html":
            path = artifacts.get("html")
        else:
            path = None
        if not path or not Path(path).resolve().is_relative_to(store.root / "files") or not Path(path).is_file():
            raise HTTPException(404, "Artifact not found")
        return FileResponse(path, filename=Path(path).name if kind == "pdf" else None)
