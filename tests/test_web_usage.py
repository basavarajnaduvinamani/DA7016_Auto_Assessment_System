"""Usage page: estimated AI cost and teacher review time across a teacher's classes."""

import json
import socket

import pytest
from fastapi.testclient import TestClient

from autoassess.web.app import create_app
from autoassess.web.usage import INR_PER_SCANNED_PAGE, INR_PER_USD, USD_PER_ANSWER, usage


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_DEMO_DRY_RUN", "1")
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("no network in tests"))
    app = create_app(tmp_path / "app")
    with TestClient(app) as client:
        client.post("/sign-in", data={"email": "demo@redink.local"})
        yield app, client


def test_usage_prices_answers_at_the_measured_rate(seeded):
    app, _ = seeded
    report = usage(app.state.store, 1)
    row = report["classes"][0]["assignments"][0]
    graded = [s for s in app.state.store.submissions(1) if s["grade_json"]]
    assert row["sheets"] == len(graded) > 0 and row["answers"] == 3 * len(graded) and row["pages"] == 0
    assert row["total_inr"] == pytest.approx(row["answers"] * USD_PER_ANSWER * INR_PER_USD)
    assert report["per_sheet_inr"] == pytest.approx(row["total_inr"] / len(graded))
    assert report["total_usd"] == pytest.approx(row["answers"] * USD_PER_ANSWER)


def test_usage_adds_scanned_pages_translation_and_review_time(seeded):
    app, _ = seeded
    store = app.state.store
    run = json.loads(store.submission(1)["run_json"])
    run["pages"] = [dict(run["pages"][0], provider="bodhan-indic-ocr", page_index=i) for i in range(3)]
    with store.connect() as db:
        db.execute("UPDATE submissions SET run_json=? WHERE id=1", (json.dumps(run),))
        db.execute("UPDATE assignments SET feedback_language='Hindi' WHERE id=1")
    store.log_review_event(1, "Q1", 1, "open", at=100.0)
    store.log_review_event(1, "Q1", 1, "accept", at=130.0)
    row = usage(store, 1)["classes"][0]["assignments"][0]
    assert row["pages"] == 3 and row["language"] == "Hindi"
    assert row["reading_inr"] == pytest.approx(3 * INR_PER_SCANNED_PAGE)
    assert row["translation_inr"] > 0
    assert row["decided"] == 1 and row["review_minutes"] == pytest.approx(0.5)


def test_usage_page_renders_and_is_private(seeded):
    _, client = seeded
    page = client.get("/usage")
    assert page.status_code == 200
    assert "What marking has cost so far" in page.text and "Generative AI · Sample quiz" in page.text
    assert "₹" in page.text and "How cost is worked out" in page.text
    assert 'href="/usage"' in client.get("/").text
    client.post("/sign-out")
    assert client.get("/usage", follow_redirects=False).status_code == 303
