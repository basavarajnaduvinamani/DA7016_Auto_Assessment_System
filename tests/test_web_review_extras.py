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
    monkeypatch.setenv('AUTOASSESS_DEMO_DRY_RUN', '1')
    monkeypatch.setenv('GRADIO_ANALYTICS_ENABLED', 'False')
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('no network in tests'))
    app = create_app(tmp_path / 'app')
    with TestClient(app) as client:
        client.post('/sign-in', data={'email': 'demo@redink.local'})
        yield app, client


def test_review_shows_the_marked_page_for_the_question(seeded):
    app, client = seeded
    page = client.get('/assignments/1/review/2/Q3').text
    assert 'Marked page' in page and '/artifact/marked?index=1' in page
    image = client.get('/assignments/1/submissions/2/artifact/marked?index=1')
    assert image.status_code == 200 and image.headers['content-type'] == 'image/png'
    pngs = json.loads(app.state.store.submission(2)['artifacts_json'])['pngs']
    assert image.content == Path(pngs[1]).read_bytes()
    assert client.get(f'/assignments/1/submissions/2/artifact/marked?index={len(pngs)}').status_code == 404


def test_review_degrades_without_marked_output(seeded):
    app, client = seeded
    store = app.state.store
    artifacts = json.loads(store.submission(1)['artifacts_json'])
    Path(artifacts['pngs'][0]).unlink()
    page = client.get('/assignments/1/review/1/Q1')
    assert page.status_code == 200 and 'Marked page' not in page.text and 'Student answer' in page.text
    assert client.get('/assignments/1/submissions/1/artifact/marked?index=0').status_code == 404
    with store.connect() as db:
        db.execute("UPDATE submissions SET artifacts_json='{}' WHERE id=1")
    assert 'Marked page' not in client.get('/assignments/1/review/1/Q1').text


def test_teacher_time_counts_auto_accepted_flagged_and_overrides(seeded):
    app, client = seeded
    store = app.state.store
    row = store.submission(1)
    grade = SheetGrade.model_validate_json(row['grade_json'])
    grade.questions[0].needs_review = True
    grade.questions[1].flags = ['possible_prompt_injection']
    grade.questions[2].confidence = 0.95
    with store.connect() as db:
        db.execute('UPDATE submissions SET grade_json=? WHERE id=1', (grade.model_dump_json(),))
    criterion = grade.questions[2].criteria[0]
    response = client.post(f'/assignments/1/review/1/{grade.questions[2].question_id}/override',
                           data={'criterion_id': criterion.criterion_id, 'marks': 0, 'reason': 'Not shown', 'version': 0})
    assert response.status_code == 200
    stats = teacher_time(store, 1)
    answers = len(store.review_rows(1))
    expected_auto = sum(1 for s in store.submissions(1) for q in SheetGrade.model_validate_json(s['grade_json']).questions
                        if not q.needs_review and q.flags in ([], ['unanswered']) and q.confidence >= 0.8)
    assert stats['answers'] == answers and stats['flagged'] >= 2 and stats['auto'] == expected_auto
    assert stats['overrides'] == 1 and stats['overridden_answers'] == 1 and stats['rechecks'] == 0
    assert stats['auto_pct'] == round(100 * expected_auto / answers)
    page = client.get('/assignments/1').text
    assert 'Where your review time goes' in page and f"{stats['auto_pct']}%" in page and 'No time-saved figure' in page


def test_teacher_time_before_grading(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOASSESS_DEMO_DRY_RUN', '1')
    app = create_app(tmp_path / 'app', seed_samples=False)
    assert teacher_time(app.state.store, 1)['auto_pct'] is None
