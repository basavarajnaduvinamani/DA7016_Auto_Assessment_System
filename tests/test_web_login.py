"""Email one-time-code sign-in: expiry, single use, attempt and request limits, demo unchanged."""

import pytest
from fastapi.testclient import TestClient

from autoassess.web import login
from autoassess.web.app import create_app
from autoassess.web.store import Store


@pytest.fixture
def mail(monkeypatch):
    """Turn email sign-in on with the in-memory mailer and a pilot list."""
    monkeypatch.setenv("AUTOASSESS_MAIL_BACKEND", "memory")
    monkeypatch.setenv("AUTOASSESS_PILOT_EMAILS", "teacher@school.edu,@pilot.org")
    monkeypatch.setenv("AUTOASSESS_SECRET_KEY", "test-secret")
    login.OUTBOX.clear()
    yield login.OUTBOX
    login.OUTBOX.clear()


@pytest.fixture
def client(tmp_path, mail):
    app = create_app(tmp_path / "app", seed_samples=False)
    with TestClient(app) as c:
        yield app, c


def last_code(outbox, email):
    return next(m["code"] for m in reversed(outbox) if m["to"] == email)


def test_code_round_trip_creates_the_teacher_and_signs_in(client, mail):
    app, c = client
    page = c.post("/sign-in", data={"email": " Teacher@School.edu "})
    assert page.status_code == 200 and "Enter your sign-in code" in page.text
    assert len(mail) == 1 and mail[0]["to"] == "teacher@school.edu" and len(mail[0]["code"]) == 6
    assert mail[0]["code"] not in str(app.state.store.teacher_by_email("teacher@school.edu"))
    signed_in = c.post("/sign-in/code", data={"email": "teacher@school.edu", "code": mail[0]["code"]})
    assert signed_in.status_code == 200 and signed_in.url.path == "/"
    teacher = app.state.store.teacher_by_email("teacher@school.edu")
    assert teacher and teacher["name"] == "teacher"
    assert "Account" in signed_in.text and "Pilot workspace." in signed_in.text


def test_code_is_single_use(client, mail):
    _, c = client
    c.post("/sign-in", data={"email": "teacher@school.edu"})
    code = last_code(mail, "teacher@school.edu")
    assert c.post("/sign-in/code", data={"email": "teacher@school.edu", "code": code}).url.path == "/"
    c.post("/sign-out")
    again = c.post("/sign-in/code", data={"email": "teacher@school.edu", "code": code})
    assert again.status_code == 400 and "already used" in again.text


def test_code_expires_after_ten_minutes(tmp_path, mail):
    store = Store(tmp_path / "s")
    assert login.request_code(store, "teacher@school.edu", "c1", now=1000.0).ok
    code = last_code(mail, "teacher@school.edu")
    late = login.verify_code(store, "teacher@school.edu", code, "c1", now=1000.0 + login.CODE_TTL + 1)
    assert not late.ok and "expired" in late.error
    assert login.request_code(store, "teacher@school.edu", "c1", now=2000.0).ok
    fresh = last_code(mail, "teacher@school.edu")
    assert login.verify_code(store, "teacher@school.edu", fresh, "c1", now=2000.0 + login.CODE_TTL - 1).ok


def test_only_the_newest_code_works(tmp_path, mail):
    store = Store(tmp_path / "s")
    login.request_code(store, "teacher@school.edu", "c1", now=100.0)
    first = last_code(mail, "teacher@school.edu")
    login.request_code(store, "teacher@school.edu", "c1", now=110.0)
    second = last_code(mail, "teacher@school.edu")
    if first != second:
        assert not login.verify_code(store, "teacher@school.edu", first, "c1", now=120.0).ok
    assert login.verify_code(store, "teacher@school.edu", second, "c1", now=121.0).ok


def test_wrong_guesses_void_the_code(tmp_path, mail):
    store = Store(tmp_path / "s")
    login.request_code(store, "teacher@school.edu", "c1", now=100.0)
    code = last_code(mail, "teacher@school.edu")
    wrong = "000000" if code != "000000" else "111111"
    for i in range(login.MAX_ATTEMPTS):
        result = login.verify_code(store, "teacher@school.edu", wrong, "c1", now=101.0 + i)
        assert not result.ok
    assert "void" in result.error
    after = login.verify_code(store, "teacher@school.edu", code, "c1", now=110.0)
    assert not after.ok and "Too many wrong tries" in after.error


def test_request_limits_per_email_and_per_client(tmp_path, mail):
    store = Store(tmp_path / "s")
    for i in range(3):
        assert login.request_code(store, "teacher@school.edu", f"c{i}", now=100.0 + i).ok
    blocked = login.request_code(store, "teacher@school.edu", "c9", now=110.0)
    assert not blocked.ok and blocked.retry_minutes > 0 and len(mail) == 3
    # The window passes.
    assert login.request_code(store, "teacher@school.edu", "c9", now=100.0 + 15 * 60 + 1).ok
    # One client asking for many different emails is stopped too.
    for i in range(10):
        login.request_code(store, f"x{i}@pilot.org", "same-client", now=5000.0 + i)
    assert not login.request_code(store, "y@pilot.org", "same-client", now=5020.0).ok


def test_failed_codes_lock_out_a_client(tmp_path, mail):
    store = Store(tmp_path / "s")
    limit, _ = login.CLIENT_FAILURES
    for i in range(limit):
        login.verify_code(store, f"nobody{i}@pilot.org", "123456", "attacker", now=100.0 + i)
    locked = login.verify_code(store, "teacher@school.edu", "123456", "attacker", now=200.0)
    assert not locked.ok and locked.retry_minutes > 0


def test_unlisted_email_gets_the_same_screen_but_no_mail(client, mail):
    _, c = client
    page = c.post("/sign-in", data={"email": "stranger@elsewhere.com"})
    assert page.status_code == 200 and "Enter your sign-in code" in page.text
    assert mail == []
    domain = c.post("/sign-in", data={"email": "new.teacher@pilot.org"})
    assert domain.status_code == 200 and mail[-1]["to"] == "new.teacher@pilot.org"


def test_demo_sign_in_is_unchanged_with_email_on(client, mail):
    _, c = client
    response = c.post("/sign-in", data={"email": "demo@redink.local"})
    assert response.status_code == 200 and response.url.path == "/" and mail == []
    # The demo account can never be reached by a code.
    assert not login.pilot_allowed(client[0].state.store, "demo@redink.local")


def test_session_cookie_dies_with_the_account(client, mail):
    app, c = client
    c.post("/sign-in", data={"email": "teacher@school.edu"})
    c.post("/sign-in/code", data={"email": "teacher@school.edu", "code": last_code(mail, "teacher@school.edu")})
    cookie = c.cookies.get("redink_session")
    teacher = app.state.store.teacher_by_email("teacher@school.edu")
    app.state.store.delete_teacher_data(teacher["id"])
    # A new account may reuse the id on SQLite; the old cookie must not open it.
    with app.state.store.connect() as db:
        db.execute("INSERT INTO teachers(id,name,email) VALUES(?,?,?)", (teacher["id"], "Other", "other@pilot.org"))
    c.cookies.set("redink_session", cookie)
    assert c.get("/", follow_redirects=False).status_code == 303


def test_landing_without_mail_keeps_the_demo_wording(tmp_path):
    with TestClient(create_app(tmp_path / "app", seed_samples=False)) as c:
        page = c.get("/sign-in").text
        assert "Demo workspace. Please use sample data only." in page and "Email me a sign-in code" not in page
        assert "How we handle your data" in page
        assert c.post("/sign-in/code", data={"email": "a@b.c", "code": "123456"}).url.path == "/sign-in"


def test_mail_failure_is_reported(tmp_path, monkeypatch, mail):
    def boom(*args):
        raise login.MailError("down")

    monkeypatch.setattr(login, "send_code", boom)
    store = Store(tmp_path / "s")
    result = login.request_code(store, "teacher@school.edu", "c1")
    assert not result.ok and "couldn't send" in result.error


def test_resend_and_brevo_payloads(monkeypatch):
    sent = []
    monkeypatch.setattr(login, "_post", lambda url, headers, payload: sent.append((url, headers, payload)))
    monkeypatch.setenv("AUTOASSESS_MAIL_FROM", "Second Read <login@school.edu>")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    login.send_code("t@school.edu", "123456")
    monkeypatch.delenv("RESEND_API_KEY")
    monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")
    login.send_code("t@school.edu", "654321")
    (resend_url, resend_headers, resend), (brevo_url, brevo_headers, brevo) = sent
    assert resend_url.endswith("/emails") and resend_headers["Authorization"] == "Bearer re_test"
    assert resend["to"] == ["t@school.edu"] and "123456" in resend["subject"]
    assert brevo_url.endswith("/smtp/email") and brevo_headers["api-key"] == "xkeysib-test"
    assert brevo["sender"] == {"name": "Second Read", "email": "login@school.edu"} and "654321" in brevo["textContent"]


def test_client_id_uses_the_proxy_appended_address(monkeypatch):
    class Req:
        client = type("C", (), {"host": "10.0.0.1"})()
        headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}

    monkeypatch.setenv("AUTOASSESS_SECRET_KEY", "k")
    direct = login.client_id(Req())
    monkeypatch.setenv("AUTOASSESS_BEHIND_PROXY", "1")
    proxied = login.client_id(Req())
    Req.headers = {"x-forwarded-for": "1.1.1.1, 203.0.113.9"}
    assert proxied != direct and login.client_id(Req()) == proxied
