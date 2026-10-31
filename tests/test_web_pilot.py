"""Pilot log export, delete-all-my-data and the privacy note."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from autoassess.cli import main
from autoassess.web import login
from autoassess.web.app import create_app
from autoassess.web.pilot import COLUMNS


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_MAIL_BACKEND", "memory")
    monkeypatch.setenv("AUTOASSESS_PILOT_EMAILS", "@school.edu")
    monkeypatch.setenv("AUTOASSESS_ADMIN_EMAILS", "lead@school.edu")
    monkeypatch.setenv("AUTOASSESS_PILOT_END", "30 November 2026")
    login.OUTBOX.clear()
    app = create_app(tmp_path / "app")
    with TestClient(app) as client:
        yield app, client


def sign_in(client, email):
    client.post("/sign-out")
    client.post("/sign-in", data={"email": email})
    code = next(m["code"] for m in reversed(login.OUTBOX) if m["to"] == email)
    return client.post("/sign-in/code", data={"email": email, "code": code})


def copy_demo_assignment(store, teacher_id):
    """Give a pilot teacher a graded assignment by copying the seeded demo sheets (synthetic data)."""
    demo = store.teacher_by_email("demo@redink.local")
    source = store.assignments(store.classes(demo["id"])[0]["id"])[0]
    class_id = store.create_class(teacher_id, "Physics 9B", "Physics")
    for roll in ("S001", "S002", "S003"):
        store.add_student(class_id, roll, f"Synthetic {roll}")
    from autoassess.schemas import ExamSpec

    assignment_id = store.create_assignment(class_id, "Unit test", ExamSpec.model_validate_json(source["spec_json"]))
    students = {s["roll_no"]: s["id"] for s in store.students(class_id)}
    for sub in store.submissions(source["id"]):
        if sub["roll_no"] not in students:
            continue
        [new_id] = store.add_submissions(assignment_id, [(students[sub["roll_no"]], sub["original_name"], sub["path"])])
        with store.connect() as db:
            db.execute(
                "UPDATE submissions SET grade_json=?, run_json=?, artifacts_json=? WHERE id=?",
                (sub["grade_json"], sub["run_json"], sub["artifacts_json"], new_id),
            )
    return assignment_id


def test_pilot_log_has_numbers_and_no_student_text(pilot):
    app, client = pilot
    store = app.state.store
    sign_in(client, "maths@school.edu")
    teacher = store.teacher_by_email("maths@school.edu")
    assignment_id = copy_demo_assignment(store, teacher["id"])
    first = store.submissions(assignment_id)[0]
    grade = store.effective_grade(first)
    question = grade.questions[0]
    criterion = question.criteria[0]
    store.log_review_event(first["id"], question.question_id, teacher["id"], "open", at=1000.0)
    store.add_override(
        first["id"], question.question_id, criterion.criterion_id, 0.0, "Secret reason text", teacher["id"],
        expected_version=0,
    )  # fmt: skip
    store.log_review_event(first["id"], question.question_id, teacher["id"], "override", at=1090.0)
    store.log_review_event(first["id"], grade.questions[1].question_id, teacher["id"], "open", at=1100.0)
    store.log_review_event(first["id"], grade.questions[1].question_id, teacher["id"], "accept", at=1130.0)

    response = client.get("/account/pilot-log.csv")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    text = response.text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0]) == COLUMNS
    summary, row = rows[0], rows[1]
    assert summary["level"] == "teacher" and row["level"] == "assignment"
    assert row["sheets_graded"] == "3" and row["sheets_reviewed"] == "1" and row["answers_decided"] == "2"
    assert row["override_rate_pct"] == "50" and row["minutes_per_sheet"] == "2.0"
    assert float(row["calibration_shift"]) == -criterion.marks_awarded and row["teacher_mark_changes"] == "1"
    assert summary["sheets_graded"] == "3" and summary["override_rate_pct"] == "50"
    for secret in (
        "Secret reason",
        "Synthetic",
        "S001",
        "maths@school.edu",
        "Physics",
        "Unit test",
        criterion.reason[:20],
    ):
        assert secret not in text

    # Only the admin may download everyone's log.
    assert client.get("/pilot/export.csv").status_code == 404
    sign_in(client, "lead@school.edu")
    everyone = client.get("/pilot/export.csv")
    demo_ref = f"T{app.state.store.teacher_by_email('demo@redink.local')['id']},"
    assert everyone.status_code == 200 and f"T{teacher['id']}," in everyone.text and demo_ref not in everyone.text


def test_pilot_export_cli(pilot, tmp_path, capsys):
    app, client = pilot
    sign_in(client, "maths@school.edu")
    out = tmp_path / "log.csv"
    assert main(["pilot-export", "--data-dir", str(app.state.store.root), "--out", str(out)]) == 0
    assert out.read_text().startswith("level,teacher_ref")


def test_delete_all_my_data_removes_everything(pilot):
    app, client = pilot
    store = app.state.store
    sign_in(client, "maths@school.edu")
    teacher = store.teacher_by_email("maths@school.edu")
    assignment_id = copy_demo_assignment(store, teacher["id"])
    folder = store.root / "files" / str(assignment_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sheet.txt").write_text("synthetic")
    store.files.save(folder / "sheet.txt")
    store.log_review_event(store.submissions(assignment_id)[0]["id"], "Q1", teacher["id"], "open", at=1.0)

    page = client.get("/account")
    assert "Delete all my data" in page.text and "30 November 2026" in page.text
    refused = client.post("/account/delete", data={"confirm": "wrong@school.edu"})
    assert refused.status_code == 400 and store.teacher_by_email("maths@school.edu")

    done = client.post("/account/delete", data={"confirm": "MATHS@school.edu"})
    assert done.url.path == "/sign-in" and "were deleted" in done.text
    assert store.teacher_by_email("maths@school.edu") is None
    assert store.assignment(assignment_id) is None and not folder.exists()
    with store.connect() as db:
        for table in ("classes", "review_events", "login_codes", "overrides"):
            column = "email" if table == "login_codes" else "teacher_id"
            value = "maths@school.edu" if table == "login_codes" else teacher["id"]
            assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (value,)).fetchone()[0] == 0
    assert store.files.blobs.keys(f"{assignment_id}/") == []
    assert client.get("/", follow_redirects=False).status_code == 303
    # The demo teacher's data is untouched.
    demo = store.teacher_by_email("demo@redink.local")
    assert store.classes(demo["id"])


def test_demo_account_cannot_be_deleted(pilot):
    app, client = pilot
    client.post("/sign-in", data={"email": "demo@redink.local"})
    response = client.post("/account/delete", data={"confirm": "demo@redink.local"})
    assert response.status_code == 400 and app.state.store.teacher_by_email("demo@redink.local")


def test_privacy_note_on_sign_in_and_public_page(pilot):
    _, client = pilot
    page = client.get("/sign-in").text
    assert "We store your email" in page and "30 November 2026" in page
    privacy = client.get("/privacy")
    assert privacy.status_code == 200 and "How long" in privacy.text and "OpenRouter" in privacy.text
