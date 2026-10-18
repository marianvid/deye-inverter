"""Each web piece mounted alone on a bare app; the password gate only where it is the subject."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from deye_inverter.web.api import MonitoringApi
from deye_inverter.web.app import WEB_ROOT
from deye_inverter.web.auth_gate import AuthGate
from deye_inverter.web.pages import PAGES, PageController
from deye_inverter.web.static_files import RevalidatedStaticFiles
from tests.conftest import Primed, World


def test_static_files_must_be_revalidated(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("console.log(1)")
    app = FastAPI()
    app.mount("/static", RevalidatedStaticFiles(directory=str(tmp_path)), name="static")
    response = TestClient(app).get("/static/app.js")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"


def test_monitoring_api_answers_from_the_services(world: World, primed: Primed) -> None:
    primed()
    app = FastAPI()
    app.include_router(MonitoringApi(world.services).router)
    client = TestClient(app)
    assert client.get("/api/now").status_code == 200
    assert client.get("/api/forecast").status_code == 200
    assert client.get("/api/history/day", params={"day": "2026-10-05"}).status_code == 200


def test_every_page_shell_renders(world: World) -> None:
    app = FastAPI()
    templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
    app.include_router(PageController(world.services, templates).router)
    client = TestClient(app)
    for path in PAGES:
        assert client.get(path).status_code == 200, path


def gated(world: World) -> TestClient:
    app = FastAPI()
    app.add_api_route("/api/now", lambda: {"ok": True})
    app.add_api_route("/setup", lambda: {"page": "setup"})
    app.add_api_route("/", lambda: {"page": "home"})
    app.add_middleware(AuthGate, passwords=world.services.passwords)
    app.add_middleware(SessionMiddleware, secret_key="test-only")
    return TestClient(app)


def test_auth_gate_sends_to_setup_then_to_login(world: World) -> None:
    client = gated(world)
    assert client.get("/", follow_redirects=False).headers["location"] == "/setup"
    assert client.get("/setup").json() == {"page": "setup"}
    world.services.passwords.set("correct horse")
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/api/now").status_code == 401
