"""Teacher shell: HTTP sessions, ownership, roster transactions and packaging."""

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoassess.cli import main
from autoassess.web.app import create_app
from autoassess.web.seed import seed
from autoassess.web.store import Store


@pytest.fixture
def teacher_app(tmp_path, monkeypatch):
    monkeypatch.setenv('GRADIO_ANALYTICS_ENABLED', 'False')
    monkeypatch.setenv('AUTOASSESS_DEMO_DRY_RUN', '1')

    def blocked(*args, **kwargs):
        pytest.fail('Teacher app tests must not use the network')

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    app = create_app(tmp_path / 'app', seed_samples=False)
    with TestClient(app) as client:
        yield app, client


def login(client):
    return client.post('/sign-in', data={'email': 'demo@redink.local'})


def test_session_guard_and_demo_sign_in(teacher_app):
    app, client = teacher_app
    for path in ['/', '/classes/1', '/classes/new', '/lab/', '/lab/config', '/docs']:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/sign-in'
    assert 'Demo sign-in. Not for real student data.' in client.get('/sign-in').text
    assert client.get('/static/htmx.min.js').status_code == 200
    assert client.get('/healthz').json() == {'ok': True, 'llm': 'fake', 'ocr': 'text'}
    response = login(client)
    assert response.status_code == 200 and 'Hello, Demo Teacher.' in response.text
    cookie = response.history[0].headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie
    assert 'DA7016 Generative AI, Section A' in response.text
    assert '10</strong> students' in response.text
    assert client.get('/lab/').status_code == 200
    assert client.get('/lab/config').status_code == 200
    client.post('/sign-out')
    assert client.get('/', follow_redirects=False).status_code == 303


def test_unknown_email_and_tampered_session_refused(teacher_app):
    _, client = teacher_app
    result = client.post('/sign-in', data={'email': 'unknown@example.org'})
    assert result.status_code == 400 and "recognise that email" in result.text
    client.cookies.set('redink_session', 'forged')
    assert client.get('/', follow_redirects=False).status_code == 303
    assert client.post('/sign-in', data={'email': ' DEMO@REDINK.LOCAL '}).status_code == 200


def test_class_create_add_student_roster_and_escape(teacher_app):
    app, client = teacher_app
    login(client)
    response = client.post('/classes', data={'name': '<script>Class</script>', 'subject': 'Science', 'section': 'B'})
    class_id = int(response.url.path.rsplit('/', 1)[1])
    assert response.status_code == 200 and '&lt;script&gt;Class&lt;/script&gt;' in response.text
    assert 'No assignments yet' in response.text
    assert client.post(f'/classes/{class_id}/students', data={'roll_no': 'R1', 'name': 'Sample One'}).status_code == 200
    roster = b'roll_no,name\nR1,Updated One\nR2,Sample Two\n'
    imported = client.post(f'/classes/{class_id}/roster', files={'roster': ('roster.csv', roster, 'text/csv')})
    assert imported.status_code == 200 and 'Imported 2 students' in imported.text
    assert [(s['roll_no'], s['name']) for s in app.state.store.students(class_id)] == [('R1', 'Updated One'), ('R2', 'Sample Two')]
    assert client.post('/classes', data={'name': ' ', 'subject': ''}).status_code == 400


@pytest.mark.parametrize('content', [b'name,roll_no\nOne,R1', b'roll_no,name\nR1,One\nR2', b'roll_no,name\nR1,One\nR1,Two', b'roll_no,name\n', b'roll_no,name\nR1,One,Extra', b'roll_no,name\nR1,One\n../bad,Two', b'\xff'])
def test_malformed_roster_is_atomic(teacher_app, content):
    app, client = teacher_app
    login(client)
    before = app.state.store.students(1)
    result = client.post('/classes/1/roster', files={'roster': ('bad.csv', content)})
    assert result.status_code == 400
    assert app.state.store.students(1) == before


def test_teacher_cannot_access_another_class(teacher_app):
    app, client = teacher_app
    with app.state.store.connect() as db:
        teacher = db.execute("INSERT INTO teachers(name,email) VALUES('Other','other@redink.local')").lastrowid
    other = app.state.store.create_class(teacher, 'Other class', 'Subject')
    login(client)
    for path in [f'/classes/{other}', '/classes/9999']:
        assert client.get(path).status_code == 404
    assert client.post(f'/classes/{other}/students', data={'roll_no': 'X', 'name': 'Name'}).status_code == 404
    assert 'Other class' not in client.get('/').text


def test_seed_is_idempotent_and_persists(tmp_path):
    store = Store(tmp_path / 'store')
    seed(store)
    seed(store)
    assert len(store.classes(1)) == 1 and len(store.students(1)) == 10
    store.add_student(1, 'S011', 'Synthetic Eleven')
    reopened = Store(tmp_path / 'store')
    seed(reopened)
    assert len(reopened.students(1)) == 11
    seed(reopened, reset=True)
    assert len(reopened.students(1)) == 10
    with store.connect() as db:
        assert [r[0] for r in db.execute('SELECT version FROM schema_version')] == [2]
    assert (store.root / 'files').is_dir()


def test_serve_cli_passes_options(monkeypatch, tmp_path):
    import autoassess.web.app as web_app
    import uvicorn

    calls = []
    sentinel = object()
    monkeypatch.setattr(web_app, 'create_app', lambda data_dir, **kwargs: calls.append((data_dir, kwargs)) or sentinel)
    monkeypatch.setattr(uvicorn, 'run', lambda app, **kwargs: calls.append((app, kwargs)))
    assert main(['serve', '--host', '127.0.0.1', '--port', '8765', '--data-dir', str(tmp_path), '--reset-demo']) == 0
    assert calls == [(str(tmp_path), {'reset_demo': True}), (sentinel, {'host': '127.0.0.1', 'port': 8765})]


def test_package_contains_templates_vendor_and_launcher():
    import tomllib
    from conftest import ROOT

    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    assert 'web/templates/*.html' in config['tool']['setuptools']['package-data']['autoassess']
    assert 'web/static/*' in config['tool']['setuptools']['package-data']['autoassess']
    assert 'from autoassess.web.lab import' in (ROOT / 'app.py').read_text()
    assert '/static/' not in (ROOT / 'src/autoassess/web/templates/base.html').read_text() or 'url_for' in (ROOT / 'src/autoassess/web/templates/base.html').read_text()
