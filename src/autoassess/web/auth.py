"""Signed teacher sessions, including the mounted lab's HTTP/WebSocket routes."""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import HTTPConnection
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from autoassess.web.store import Store


_PROCESS_SECRET = secrets.token_hex(32)
COOKIE = "redink_session"
MAX_AGE = 12 * 60 * 60


def secret_key() -> str:
    """The configured AUTOASSESS_SECRET_KEY, or a per-process random secret (sessions end on restart)."""
    return os.getenv("AUTOASSESS_SECRET_KEY") or _PROCESS_SECRET


def signer() -> URLSafeTimedSerializer:
    """Create the timed session signer using the configured secret."""
    return URLSafeTimedSerializer(secret_key(), salt="redink-demo-session")


def session_token(serializer: URLSafeTimedSerializer, teacher: dict) -> str:
    """Sign a session for one teacher: id plus email, so a reused id never inherits a deleted account's cookie."""
    return serializer.dumps([teacher["id"], teacher["email"].lower()])


PUBLIC_PATHS = ("/sign-in", "/sign-in/code", "/healthz", "/privacy")


class DemoSession:
    """Require a signed teacher session for protected HTTP and WebSocket routes."""

    def __init__(self, app: ASGIApp, store: Store, serializer: URLSafeTimedSerializer) -> None:
        self.app, self.store, self.serializer = app, store, serializer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return await self.app(scope, receive, send)
        token = HTTPConnection(scope).cookies.get(COOKIE, "")
        try:
            payload = self.serializer.loads(token, max_age=MAX_AGE)
            teacher_id, email = payload if isinstance(payload, list) and len(payload) == 2 else (None, None)
            teacher = self.store.teacher(teacher_id) if isinstance(teacher_id, int) else None
            if teacher is not None and teacher["email"].lower() != email:
                teacher = None
        except (BadSignature, SignatureExpired, ValueError, TypeError):
            teacher = None
        if teacher is None:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 4401})
            return await RedirectResponse("/sign-in", status_code=303)(scope, receive, send)
        scope.setdefault("state", {})["teacher"] = teacher
        await self.app(scope, receive, send)
