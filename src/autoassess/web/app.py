"""One-process teacher app, with the existing Gradio lab mounted lazily."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from autoassess.demo import health_payload
from autoassess.web.auth import COOKIE, MAX_AGE, DemoSession, signer
from autoassess.web.downloads import mount_download_routes
from autoassess.web.jobs import Jobs
from autoassess.web.routes import mount_assignment_routes
from autoassess.web.seed import seed, seed_assignment
from autoassess.web.store import Store

HERE = Path(__file__).resolve().parent


def create_app(data_dir: str | Path | None = None, *, reset_demo: bool = False, seed_samples: bool = True) -> FastAPI:
    """Create the teacher app, initialise local data and mount the Gradio lab.

    Args:
        data_dir: SQLite and artifact directory; defaults to the environment or .redink.
        reset_demo: Replace local records with the synthetic demonstration seed.
        seed_samples: Pre-grade packaged examples with the offline provider on first start.

    Returns:
        The authenticated teacher application with its lab mounted at /lab.
    """
    store = Store(data_dir or os.getenv("AUTOASSESS_DATA_DIR", ".redink"))
    seed(store, reset=reset_demo)
    if seed_samples:
        seed_assignment(store)
    jobs = Jobs(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Resume queued work at startup and close workers during shutdown."""
        jobs.start()
        try:
            yield
        finally:
            jobs.close()

    serializer = signer()
    app = FastAPI(title="Red-Ink Classroom", lifespan=lifespan)
    app.state.jobs = jobs
    app.state.store = store
    templates = Jinja2Templates(directory=HERE / "templates")
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.add_middleware(DemoSession, store=store, serializer=serializer)

    def render(request: Request, name: str, **context: Any) -> Response:
        """Render a teacher template with the current session context."""
        return templates.TemplateResponse(
            request=request, name=name, context={"teacher": getattr(request.state, "teacher", None), **context}
        )

    def classroom(request: Request, class_id: int) -> dict[str, Any]:
        """Find a class owned by the signed-in teacher or return 404."""
        result = store.classroom(class_id, request.state.teacher["id"])
        if result is None:
            raise HTTPException(404, "Class not found")
        return result

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        """Return readiness metadata without contacting providers."""
        return health_payload()

    @app.get("/sign-in")
    def sign_in(request: Request) -> Response:
        """Render the demo teacher sign-in page."""
        return render(request, "sign_in.html")

    @app.post("/sign-in")
    def continue_sign_in(request: Request, email: str = Form("")) -> Response:
        """Set a signed session cookie for a known seeded teacher."""
        teacher = store.teacher_by_email(email)
        if teacher is None:
            response = render(
                request, "sign_in.html", error="We don't recognise that email. Try the demo teacher below.", email=email
            )
            response.status_code = 400
            return response
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE,
            serializer.dumps(teacher["id"]),
            max_age=MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response

    @app.post("/sign-out")
    def sign_out() -> Response:
        """Clear the demo session cookie and return to sign-in."""
        response = RedirectResponse("/sign-in", status_code=303)
        response.delete_cookie(COOKIE, httponly=True, samesite="lax")
        return response

    @app.get("/")
    def dashboard(request: Request) -> Response:
        """Show class cards and current review counts for this teacher."""
        return render(request, "dashboard.html", classes=store.classes(request.state.teacher["id"]))

    @app.get("/classes/new")
    def new_class(request: Request) -> Response:
        """Show the class-creation form."""
        return render(request, "new_class.html")

    @app.post("/classes")
    def save_class(
        request: Request, name: str = Form(""), subject: str = Form(""), section: str = Form("")
    ) -> Response:
        """Validate class fields and persist a teacher-owned class."""
        try:
            class_id = store.create_class(request.state.teacher["id"], name, subject, section)
        except ValueError as err:
            response = render(
                request, "new_class.html", error=str(err), values={"name": name, "subject": subject, "section": section}
            )
            response.status_code = 400
            return response
        return RedirectResponse(f"/classes/{class_id}", status_code=303)

    @app.get("/classes/{class_id}")
    def class_page(request: Request, class_id: int) -> Response:
        """Show the roster and assignments for an owned class."""
        return render(
            request,
            "class.html",
            classroom=classroom(request, class_id),
            students=store.students(class_id),
            assignments=store.assignments(class_id),
        )

    def roster_result(
        request: Request, class_id: int, error: str | None = None, message: str | None = None
    ) -> Response:
        """Render roster validation feedback without losing the class context."""
        response = render(
            request,
            "class.html",
            classroom=classroom(request, class_id),
            students=store.students(class_id),
            assignments=store.assignments(class_id),
            error=error,
            message=message,
        )
        response.status_code = 400 if error else 200
        return response

    @app.post("/classes/{class_id}/students")
    def add_student(request: Request, class_id: int, roll_no: str = Form(""), name: str = Form("")) -> Response:
        """Validate and upsert one student in an owned class."""
        classroom(request, class_id)
        try:
            store.add_student(class_id, roll_no, name)
        except ValueError as err:
            return roster_result(request, class_id, error=str(err))
        return RedirectResponse(f"/classes/{class_id}", status_code=303)

    @app.post("/classes/{class_id}/roster")
    async def import_roster(request: Request, class_id: int, roster: UploadFile = File(...)) -> Response:
        """Import a bounded CSV roster atomically after validating every row."""
        classroom(request, class_id)
        try:
            count = store.import_roster(class_id, await roster.read(1024 * 1024 + 1))
        except ValueError as err:
            return roster_result(request, class_id, error=str(err))
        return roster_result(
            request, class_id, message=f"Imported {count} students. Existing roll numbers were updated."
        )

    mount_assignment_routes(app, store, templates, jobs)
    mount_download_routes(app, store, templates)

    # Packaging the lab keeps non-editable installations independent of repo app.py.
    import gradio as gr

    from autoassess.web.lab import demo

    return gr.mount_gradio_app(
        app,
        demo.queue(default_concurrency_limit=2),
        path="/lab",
        show_error=False,
        max_file_size=int(float(os.getenv("AUTOASSESS_MAX_UPLOAD_MB", "10")) * 1024 * 1024),
    )
