"""HTML pages: each page is a shell; its JavaScript loads the data from the API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from deye_inverter.application.auth import PasswordError
from deye_inverter.container import Services
from deye_inverter.web.auth_gate import SESSION_FLAG

PAGES = {
    "/": ("now", "Now"),
    "/statistics": ("statistics", "Statistics"),
    "/forecast": ("forecast", "Forecast"),
    "/plan": ("plan", "Plan"),
    "/time-of-use": ("tou", "Time of Use"),
    "/settings": ("settings", "Settings"),
    "/log": ("log", "Log"),
}


class PageController:
    def __init__(self, services: Services, templates: Jinja2Templates) -> None:
        self._services = services
        self._templates = templates
        self.router = APIRouter(include_in_schema=False)
        for path, (name, title) in PAGES.items():
            self.router.add_api_route(
                path, self._page(name, title), methods=["GET"], response_class=HTMLResponse
            )
        self.router.add_api_route("/setup", self.setup_form, methods=["GET"])
        self.router.add_api_route("/setup", self.setup_submit, methods=["POST"])
        self.router.add_api_route("/login", self.login_form, methods=["GET"])
        self.router.add_api_route("/login", self.login_submit, methods=["POST"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"])

    def _page(self, name: str, title: str):  # type: ignore[no-untyped-def]
        def render(request: Request) -> Response:
            context = {"page": name, "title": title, "pages": PAGES}
            return self._templates.TemplateResponse(request, f"{name}.html", context)

        return render

    def setup_form(self, request: Request) -> Response:
        if self._services.passwords.is_set():
            return RedirectResponse("/login", status_code=303)
        return self._form(request, "setup.html", error=None)

    def setup_submit(
        self, request: Request, password: Annotated[str, Form()], confirm: Annotated[str, Form()]
    ) -> Response:
        if self._services.passwords.is_set():
            return RedirectResponse("/login", status_code=303)
        if password != confirm:
            return self._form(request, "setup.html", error="The two passwords differ.")
        try:
            self._services.passwords.set(password)
        except PasswordError as error:
            return self._form(request, "setup.html", error=str(error))
        request.session[SESSION_FLAG] = True
        return RedirectResponse("/", status_code=303)

    def login_form(self, request: Request) -> Response:
        return self._form(request, "login.html", error=None)

    def login_submit(self, request: Request, password: Annotated[str, Form()]) -> Response:
        if not self._services.passwords.verify(password):
            return self._form(request, "login.html", error="Wrong password.")
        request.session[SESSION_FLAG] = True
        return RedirectResponse("/", status_code=303)

    @staticmethod
    def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    def _form(self, request: Request, template: str, error: str | None) -> Response:
        return self._templates.TemplateResponse(request, template, {"error": error})
