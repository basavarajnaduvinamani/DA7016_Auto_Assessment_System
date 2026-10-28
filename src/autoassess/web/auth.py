"""Signed demo sessions, including the mounted lab's HTTP/WebSocket routes."""

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


def signer() -> URLSafeTimedSerializer:
    """Create the timed demo-session signer using the configured process secret."""
    return URLSafeTimedSerializer(os.getenv("AUTOASSESS_SECRET_KEY") or _PROCESS_SECRET, salt="redink-demo-session")


class DemoSession:
    """Require a signed teacher session for protected HTTP and WebSocket routes."""

    def __init__(self, app: ASGIApp, store: Store, serializer: URLSafeTimedSerializer) -> None:
        self.app, self.store, self.serializer = app, store, serializer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in ("/sign-in", "/healthz") or path.startswith("/static/"):
            return await self.app(scope, receive, send)
        token = HTTPConnection(scope).cookies.get(COOKIE, "")
        try:
            teacher_id = self.serializer.loads(token, max_age=MAX_AGE)
            teacher = self.store.teacher(teacher_id) if isinstance(teacher_id, int) else None
        except (BadSignature, SignatureExpired):
            teacher = None
        if teacher is None:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 4401})
            return await RedirectResponse("/sign-in", status_code=303)(scope, receive, send)
        scope.setdefault("state", {})["teacher"] = teacher
        await self.app(scope, receive, send)
