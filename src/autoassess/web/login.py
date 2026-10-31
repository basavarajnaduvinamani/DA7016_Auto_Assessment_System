"""Email sign-in with one-time codes: 6 digits, 10 minutes, single use, rate limited.

The flow: a teacher enters an email, gets a code by email, and types it in. Only a keyed hash
of each code is stored. A code dies at its first correct use, after ``MAX_ATTEMPTS`` wrong
guesses, when a newer code is sent, or after ``CODE_TTL`` seconds.

Who may sign in: an existing teacher, or an email on the ``AUTOASSESS_PILOT_EMAILS`` list
(addresses or ``@school.edu`` domains, comma separated). The answer on screen is the same
either way, so the form does not reveal who is on the list. The shared demo teacher keeps
its one-click sign-in and never needs a code.

Mail is sent through an HTTPS API (Render's free tier and most hosts block SMTP ports):
``RESEND_API_KEY`` (Resend) or ``BREVO_API_KEY`` (Brevo), with ``AUTOASSESS_MAIL_FROM`` as
the sender. ``AUTOASSESS_MAIL_BACKEND=console`` prints codes to the server log for local runs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

from autoassess.web.store import normal_email

if TYPE_CHECKING:
    from starlette.requests import Request

    from autoassess.web.store import Store

DEMO_EMAIL = "demo@redink.local"
CODE_TTL = 10 * 60  # seconds a code stays valid
MAX_ATTEMPTS = 5  # wrong guesses before a code is void
# (count, window seconds): at most this many codes per email / requests per client in the window.
EMAIL_LIMITS = ((3, 15 * 60), (10, 24 * 60 * 60))
CLIENT_LIMITS = ((10, 60 * 60),)
# Wrong codes from one client before it is locked out for the window.
CLIENT_FAILURES = (20, 15 * 60)
LOG_KEEP = 24 * 60 * 60  # rate-limit rows older than a day are deleted

# Codes sent by the "memory" backend, for tests.
OUTBOX: list[dict[str, str]] = []


@dataclass
class Outcome:
    """What happened to a sign-in request: ok, or a message for the teacher."""

    ok: bool
    error: str = ""
    retry_minutes: int = 0


def mail_backend() -> str:
    """The configured mail backend: resend, brevo, console, memory, or '' when email sign-in is off."""
    explicit = os.getenv("AUTOASSESS_MAIL_BACKEND", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("BREVO_API_KEY"):
        return "brevo"
    return ""


def email_sign_in_enabled() -> bool:
    """True when the server can send sign-in codes."""
    return mail_backend() in ("resend", "brevo", "console", "memory")


def _secret() -> bytes:
    from autoassess.web.auth import secret_key

    return secret_key().encode()


def code_hash(email: str, code: str) -> str:
    """Keyed hash of an email and code; the code itself is never stored."""
    return hmac.new(_secret(), f"{normal_email(email)}:{code.strip()}".encode(), hashlib.sha256).hexdigest()


def client_id(request: Request) -> str:
    """A hashed client address for rate limits (raw IP addresses are never stored).

    Behind a proxy that appends the caller's address to X-Forwarded-For (Render does), set
    ``AUTOASSESS_BEHIND_PROXY=1`` so the last entry is used; earlier entries can be forged.
    """
    address = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and os.getenv("AUTOASSESS_BEHIND_PROXY", "") == "1":
        address = forwarded.split(",")[-1].strip() or address
    return hashlib.sha256(_secret() + address.encode()).hexdigest()[:24]


def pilot_allowed(store: Store, email: str) -> bool:
    """An existing (non-demo) teacher, or an address or domain on AUTOASSESS_PILOT_EMAILS."""
    email = normal_email(email)
    if not email or "@" not in email or email == DEMO_EMAIL:
        return False
    if store.teacher_by_email(email):
        return True
    entries = [e.strip().lower() for e in os.getenv("AUTOASSESS_PILOT_EMAILS", "").split(",") if e.strip()]
    domain = "@" + email.split("@", 1)[1]
    return "*" in entries or email in entries or domain in entries


def _over_limit(store: Store, column: str, value: str, kind: str, limits, now: float) -> int:
    """Minutes until the earliest window frees up, or 0 when under every limit."""
    wait = 0
    with store.connect() as db:
        for count, window in limits:
            rows = db.execute(
                f"SELECT at FROM login_requests WHERE {column}=? AND kind=? AND at>? ORDER BY at",
                (value, kind, now - window),
            ).fetchall()
            if len(rows) >= count:
                wait = max(wait, int((rows[0][0] + window - now) // 60) + 1)
    return wait


def _log(store: Store, email: str, client: str, kind: str, now: float) -> None:
    with store.connect() as db:
        db.execute("DELETE FROM login_requests WHERE at<?", (now - LOG_KEEP,))
        db.execute("INSERT INTO login_requests(email,client,kind,at) VALUES(?,?,?,?)", (email, client, kind, now))


def request_code(store: Store, email: str, client: str, *, now: float | None = None) -> Outcome:
    """Send a fresh code if the email may sign in; rate limits apply whether or not it may."""
    now = time.time() if now is None else now
    email = normal_email(email)
    if not email or "@" not in email or len(email) > 254:
        return Outcome(False, "Enter a valid email address.")
    wait = max(
        _over_limit(store, "client", client, "request", CLIENT_LIMITS, now),
        _over_limit(store, "email", email, "request", EMAIL_LIMITS, now),
    )
    if wait:
        return Outcome(False, f"Too many sign-in requests. Try again in {wait} minute{'s' if wait != 1 else ''}.", wait)
    _log(store, email, client, "request", now)
    if not pilot_allowed(store, email):
        return Outcome(True)  # same screen as a real send, so the list of teachers stays private
    code = f"{secrets.randbelow(10**6):06d}"
    with store.connect() as db:
        # Only the newest code works.
        db.execute("UPDATE login_codes SET used_at=? WHERE email=? AND used_at IS NULL", (now, email))
        db.execute(
            "INSERT INTO login_codes(email,code_hash,created_at,expires_at) VALUES(?,?,?,?)",
            (email, code_hash(email, code), now, now + CODE_TTL),
        )
    try:
        send_code(email, code)
    except MailError:
        return Outcome(False, "We couldn't send the email just now. Please try again in a minute.")
    return Outcome(True)


def verify_code(store: Store, email: str, code: str, client: str, *, now: float | None = None) -> Outcome:
    """Check a code; on success it is spent and the teacher account exists. ``error`` explains a refusal."""
    now = time.time() if now is None else now
    email, code = normal_email(email), "".join(ch for ch in (code or "") if ch.isdigit())
    wait = _over_limit(store, "client", client, "fail", (CLIENT_FAILURES,), now)
    if wait:
        return Outcome(False, f"Too many wrong codes. Try again in {wait} minute{'s' if wait != 1 else ''}.", wait)
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM login_codes WHERE email=? AND used_at IS NULL ORDER BY id DESC LIMIT 1", (email,)
        ).fetchone()
    if row is None or row["expires_at"] <= now:
        _log(store, email, client, "fail", now)
        return Outcome(False, "That code has expired or was already used. Request a new one.")
    if row["attempts"] >= MAX_ATTEMPTS:
        _log(store, email, client, "fail", now)
        return Outcome(False, "Too many wrong tries for this code. Request a new one.")
    if len(code) != 6 or not hmac.compare_digest(code_hash(email, code), row["code_hash"]):
        with store.connect() as db:
            db.execute("UPDATE login_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
        _log(store, email, client, "fail", now)
        left = MAX_ATTEMPTS - row["attempts"] - 1
        return Outcome(
            False,
            f"That code isn't right. {left} tr{'ies' if left != 1 else 'y'} left."
            if left
            else "That code isn't right, and it is now void. Request a new one.",
        )
    with store.connect() as db:
        # The guarded update makes the code single-use even if two tabs submit it at once.
        spent = db.execute("UPDATE login_codes SET used_at=? WHERE id=? AND used_at IS NULL", (now, row["id"])).rowcount
    if spent != 1:
        return Outcome(False, "That code has expired or was already used. Request a new one.")
    store.create_teacher(email)
    return Outcome(True)


class MailError(RuntimeError):
    """The mail provider refused or could not be reached."""


def _message(code: str) -> tuple[str, str, str]:
    from autoassess.web.landing import NAME

    subject = f"{code} is your {NAME} sign-in code"
    text = (
        f"Your {NAME} sign-in code is {code}\n\n"
        "It works once and expires in 10 minutes. If you didn't ask for it, you can ignore this email."
    )
    html = (
        f"<p>Your {NAME} sign-in code is</p><p style='font-size:28px;letter-spacing:4px'><strong>{code}</strong></p>"
        "<p>It works once and expires in 10 minutes. If you didn't ask for it, you can ignore this email.</p>"
    )
    return subject, text, html


def _post(url: str, headers: dict[str, str], payload: dict) -> None:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise MailError(f"mail API returned {response.status}")
    except (urllib.error.URLError, TimeoutError) as err:
        raise MailError(str(err)) from err


def send_code(email: str, code: str) -> None:
    """Email a sign-in code through the configured backend."""
    backend = mail_backend()
    subject, text, html = _message(code)
    sender = os.getenv("AUTOASSESS_MAIL_FROM", "Second Read <onboarding@resend.dev>")
    if backend == "memory":
        OUTBOX.append({"to": email, "code": code, "subject": subject})
    elif backend == "console":
        print(f"[sign-in] code for {email}: {code}", flush=True)
    elif backend == "resend":
        _post(
            "https://api.resend.com/emails",
            {"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            {"from": sender, "to": [email], "subject": subject, "text": text, "html": html},
        )
    elif backend == "brevo":
        name, _, address = sender.rpartition("<")
        sender_obj = {"name": name.strip() or "Second Read", "email": address.rstrip(">").strip() or sender}
        _post(
            "https://api.brevo.com/v3/smtp/email",
            {"api-key": os.environ["BREVO_API_KEY"], "accept": "application/json"},
            {
                "sender": sender_obj,
                "to": [{"email": email}],
                "subject": subject,
                "textContent": text,
                "htmlContent": html,
            },
        )
    else:
        raise MailError("Email sign-in is not configured.")
