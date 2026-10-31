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
from autoassess.web.auth import COOKIE, MAX_AGE, DemoSession, session_token, signer
from autoassess.web.downloads import mount_download_routes
from autoassess.web.jobs import Jobs
from autoassess.web.landing import FEATURES, LANGUAGE_NAMES, NAME, PROMISE, REPO_URL, STEPS, TAGLINE, privacy_note
from autoassess.web.login import DEMO_EMAIL, client_id, email_sign_in_enabled, request_code, verify_code
from autoassess.web.pilot import all_rows, teacher_rows
from autoassess.web.pilot import to_csv as pilot_csv
from autoassess.web.presentation import flag_chips
from autoassess.web.routes import mount_assignment_routes
from autoassess.web.seed import seed, seed_assignment
from autoassess.web.store import Store, normal_email
from autoassess.web.usage import usage

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
    app = FastAPI(title=NAME, lifespan=lifespan)
    app.state.jobs = jobs
    app.state.store = store
    templates = Jinja2Templates(directory=HERE / "templates")
    # One product name for every page, so a rename touches landing.NAME only.
    templates.env.globals["product_name"] = NAME
    templates.env.globals["pilot_mode"] = email_sign_in_enabled()
    app.state.templates = templates
    templates.env.globals["flag_chips"] = flag_chips
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

    def landing(request: Request, **context: Any) -> Response:
        """Render the public page shown before sign-in: the product, how it works, languages, then demo sign-in."""
        return render(
            request,
            "sign_in.html",
            repo_url=REPO_URL,
            tagline=TAGLINE,
            promise=PROMISE,
            features=FEATURES,
            steps=STEPS,
            languages=LANGUAGE_NAMES,
            email_sign_in=email_sign_in_enabled(),
            privacy=privacy_note(),
            **context,
        )

    def start_session(request: Request, teacher: dict[str, Any], to: str = "/") -> Response:
        """Redirect with a signed session cookie for one teacher."""
        response = RedirectResponse(to, status_code=303)
        forwarded_https = (
            os.getenv("AUTOASSESS_BEHIND_PROXY") == "1" and request.headers.get("x-forwarded-proto") == "https"
        )
        response.set_cookie(
            COOKIE,
            session_token(serializer, teacher),
            max_age=MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https" or forwarded_https,
        )
        return response

    def code_page(request: Request, email: str, status: int = 200, **context: Any) -> Response:
        """The 'check your email' step with the code form."""
        response = render(request, "sign_in_code.html", email=email, privacy=privacy_note(), **context)
        response.status_code = status
        return response

    @app.get("/sign-in")
    def sign_in(request: Request) -> Response:
        """Render the public landing page with the sign-in forms."""
        deleted = request.query_params.get("deleted") == "1"
        return landing(request, message="Your account and all its data were deleted." if deleted else None)

    @app.post("/sign-in")
    def continue_sign_in(request: Request, email: str = Form("")) -> Response:
        """Sign the demo teacher straight in; email anyone else a one-time code."""
        if normal_email(email) == DEMO_EMAIL:
            return start_session(request, store.teacher_by_email(DEMO_EMAIL))
        if not email_sign_in_enabled():
            response = landing(request, error="We don't recognise that email. Try the demo teacher below.", email=email)
            response.status_code = 400
            return response
        outcome = request_code(store, email, client_id(request))
        if not outcome.ok:
            response = landing(request, error=outcome.error, email=email)
            response.status_code = 429 if outcome.retry_minutes else 400
            return response
        return code_page(request, normal_email(email))

    @app.post("/sign-in/code")
    def verify_sign_in(request: Request, email: str = Form(""), code: str = Form("")) -> Response:
        """Check a one-time code and start a session."""
        if not email_sign_in_enabled():
            return RedirectResponse("/sign-in", status_code=303)
        outcome = verify_code(store, email, code, client_id(request))
        if not outcome.ok:
            return code_page(
                request, normal_email(email), status=429 if outcome.retry_minutes else 400, error=outcome.error
            )
        return start_session(request, store.teacher_by_email(email))

    @app.get("/privacy")
    def privacy(request: Request) -> Response:
        """What is stored, where and for how long."""
        return render(request, "privacy.html", privacy=privacy_note())

    @app.post("/sign-out")
    def sign_out() -> Response:
        """Clear the session cookie and return to sign-in."""
        response = RedirectResponse("/sign-in", status_code=303)
        response.delete_cookie(COOKIE, httponly=True, samesite="lax")
        return response

    def is_admin(teacher: dict[str, Any]) -> bool:
        """Teachers on AUTOASSESS_ADMIN_EMAILS may download the whole pilot's log."""
        admins = {e.strip().lower() for e in os.getenv("AUTOASSESS_ADMIN_EMAILS", "").split(",") if e.strip()}
        return teacher["email"].lower() in admins

    @app.get("/account")
    def account(request: Request) -> Response:
        """Privacy note, pilot-log download and the delete-everything button."""
        teacher = request.state.teacher
        return render(
            request,
            "account.html",
            privacy=privacy_note(),
            is_demo=teacher["email"].lower() == DEMO_EMAIL,
            is_admin=is_admin(teacher),
        )

    def csv_download(content: bytes, filename: str) -> Response:
        """Send CSV bytes as an uncached attachment."""
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
        )

    @app.get("/account/pilot-log.csv")
    def my_pilot_log(request: Request) -> Response:
        """This teacher's pilot log: counts and timings only, no student text."""
        teacher = request.state.teacher
        return csv_download(
            pilot_csv(teacher_rows(store, teacher["id"])), f"second-read-pilot-log-T{teacher['id']}.csv"
        )

    @app.get("/pilot/export.csv")
    def pilot_export(request: Request) -> Response:
        """Every pilot teacher's log, for the people running the pilot (AUTOASSESS_ADMIN_EMAILS)."""
        if not is_admin(request.state.teacher):
            raise HTTPException(404, "Not found")
        return csv_download(pilot_csv(all_rows(store)), "second-read-pilot-log-all.csv")

    @app.post("/account/delete")
    def delete_account(request: Request, confirm: str = Form("")) -> Response:
        """Delete the signed-in teacher and everything they own, after they type their email to confirm."""
        teacher = request.state.teacher
        if teacher["email"].lower() == DEMO_EMAIL:
            response = render(
                request,
                "account.html",
                privacy=privacy_note(),
                is_demo=True,
                is_admin=is_admin(teacher),
                error="The shared demo account can't be deleted. Sign in with your own email to delete your data.",
            )
            response.status_code = 400
            return response
        if normal_email(confirm) != teacher["email"].lower():
            response = render(
                request,
                "account.html",
                privacy=privacy_note(),
                is_demo=False,
                is_admin=is_admin(teacher),
                error="Type your email address exactly to confirm. Nothing was deleted.",
            )
            response.status_code = 400
            return response
        store.delete_teacher_data(teacher["id"])
        response = RedirectResponse("/sign-in?deleted=1", status_code=303)
        response.delete_cookie(COOKIE, httponly=True, samesite="lax")
        return response

    @app.get("/")
    def dashboard(request: Request) -> Response:
        """Show class cards and current review counts for this teacher."""
        return render(request, "dashboard.html", classes=store.classes(request.state.teacher["id"]))

    @app.get("/usage")
    def usage_page(request: Request) -> Response:
        """Show estimated AI cost and teacher review time for every class and assignment."""
        return render(request, "usage.html", usage=usage(store, request.state.teacher["id"]))

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

    from autoassess.web.brand import CSS, THEME
    from autoassess.web.lab import demo

    return gr.mount_gradio_app(
        app,
        demo.queue(default_concurrency_limit=2),
        path="/lab",
        show_error=False,
        theme=THEME,
        css=CSS,
        max_file_size=int(float(os.getenv("AUTOASSESS_MAX_UPLOAD_MB", "10")) * 1024 * 1024),
    )
