"""Middleware that lets a request through only after the password is set and entered."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp

from deye_inverter.application.auth import PasswordService

OPEN_PATHS = ("/static/", "/login", "/setup")
SESSION_FLAG = "authenticated"


class AuthGate(BaseHTTPMiddleware):  # type: ignore[misc,unused-ignore]
    def __init__(self, app: ASGIApp, passwords: PasswordService) -> None:
        super().__init__(app)
        self._passwords = passwords

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not self._passwords.is_set():
            if path.startswith(("/static/", "/setup")):
                return await call_next(request)
            return self._deny(path, "/setup")
        if path.startswith(OPEN_PATHS) or request.session.get(SESSION_FLAG):
            return await call_next(request)
        return self._deny(path, "/login")

    @staticmethod
    def _deny(path: str, page: str) -> Response:
        if path.startswith("/api/"):
            return JSONResponse({"error": "login required"}, status_code=401)
        return RedirectResponse(page, status_code=303)
