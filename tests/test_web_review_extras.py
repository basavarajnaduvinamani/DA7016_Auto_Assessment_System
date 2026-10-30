"""Review screen marked page and the assignment's teacher-time card."""

import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoassess.schemas import SheetGrade
from autoassess.web.app import create_app
from autoassess.web.teacher_time import teacher_time


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_DEMO_DRY_RUN", "1")
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("no network in tests"))
    app = create_app(tmp_path / "app")
    with TestClient(app) as client:
        client.post("/sign-in", data={"email": "demo@redink.local"})
        yield app, client


def test_review_shows_the_marked_page_for_the_question(seeded):
    app, client = seeded
    page = client.get("/assignments/1/review/2/Q3").text
    assert "Marked page" in page and "/artifact/marked?index=1" in page
    image = client.get("/assignments/1/submissions/2/artifact/marked?index=1")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    pngs = json.loads(app.state.store.submission(2)["artifacts_json"])["pngs"]
    assert image.content == Path(pngs[1]).read_bytes()
    assert client.get(f"/assignments/1/submissions/2/artifact/marked?index={len(pngs)}").status_code == 404


def test_review_degrades_without_marked_output(seeded):
    app, client = seeded
    store = app.state.store
    artifacts = json.loads(store.submission(1)["artifacts_json"])
    Path(artifacts["pngs"][0]).unlink()
    page = client.get("/assignments/1/review/1/Q1")
    assert page.status_code == 200 and "Marked page" not in page.text and "Student answer" in page.text
    assert client.get("/assignments/1/submissions/1/artifact/marked?index=0").status_code == 404
    with store.connect() as db:
        db.execute("UPDATE submissions SET artifacts_json='{}' WHERE id=1")
    assert "Marked page" not in client.get("/assignments/1/review/1/Q1").text


def test_teacher_time_counts_auto_accepted_flagged_and_overrides(seeded):
    app, client = seeded
    store = app.state.store
    row = store.submission(1)
    grade = SheetGrade.model_validate_json(row["grade_json"])
    grade.questions[0].needs_review = True
    grade.questions[1].flags = ["possible_prompt_injection"]
    grade.questions[2].confidence = 0.95
    with store.connect() as db:
        db.execute("UPDATE submissions SET grade_json=? WHERE id=1", (grade.model_dump_json(),))
    criterion = grade.questions[2].criteria[0]
    response = client.post(
        f"/assignments/1/review/1/{grade.questions[2].question_id}/override",
        data={"criterion_id": criterion.criterion_id, "marks": 0, "reason": "Not shown", "version": 0},
    )
    assert response.status_code == 200
    stats = teacher_time(store, 1)
    answers = len(store.review_rows(1))
    expected_auto = sum(
        1
        for s in store.submissions(1)
        for q in SheetGrade.model_validate_json(s["grade_json"]).questions
        if not q.needs_review and q.flags in ([], ["unanswered"]) and q.confidence >= 0.8
    )
    assert stats["answers"] == answers and stats["flagged"] >= 2 and stats["auto"] == expected_auto
    assert stats["overrides"] == 1 and stats["overridden_answers"] == 1 and stats["rechecks"] == 0
    assert stats["auto_pct"] == round(100 * expected_auto / answers)
    page = client.get("/assignments/1").text
    assert (
        "Where your review time goes" in page
        and f"{stats['auto_pct']}%" in page
        and "pauses over 15 minutes are left out" in page
    )


def test_teacher_time_before_grading(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_DEMO_DRY_RUN", "1")
    app = create_app(tmp_path / "app", seed_samples=False)
    assert teacher_time(app.state.store, 1)["auto_pct"] is None


def test_review_activity_counts_overrides_and_time():
    from autoassess.web.teacher_time import review_activity

    events = [
        {"submission_id": 1, "question_id": "Q1", "kind": "open", "at": 100.0},
        {"submission_id": 1, "question_id": "Q1", "kind": "accept", "at": 130.0},
        {"submission_id": 1, "question_id": "Q2", "kind": "open", "at": 200.0},
        {"submission_id": 1, "question_id": "Q2", "kind": "override", "at": 290.0},
        # Opened, then left for an hour: decided but not timed.
        {"submission_id": 2, "question_id": "Q1", "kind": "open", "at": 1000.0},
        {"submission_id": 2, "question_id": "Q1", "kind": "accept", "at": 4600.0},
        # Opened but never decided.
        {"submission_id": 2, "question_id": "Q2", "kind": "open", "at": 5000.0},
    ]
    activity = review_activity(events)
    assert activity["decided"] == 3 and activity["override_rate_pct"] == 33
    assert activity["median_review_seconds"] == 60 and activity["review_minutes"] == 2.0
    assert review_activity([])["override_rate_pct"] is None


def test_opening_and_accepting_an_answer_is_logged_and_shown(seeded):
    app, client = seeded
    assert client.get("/assignments/1/review/2/Q1").status_code == 200
    assert client.post("/assignments/1/review/2/Q1/accept").status_code == 200
    kinds = [e["kind"] for e in app.state.store.review_events(1)]
    assert kinds == ["open", "accept"]
    page = client.get("/assignments/1").text
    assert "Override rate" in page and "Answers you decided" in page
