import pytest
from fastapi.testclient import TestClient

from deye_inverter.domain.time_of_use import table_to_dicts
from deye_inverter.web.app import create_app
from tests.fakes import winter_table

PASSWORD = "correct horse"


@pytest.fixture
def client(world, primed):
    primed()
    with TestClient(create_app(world.services)) as test_client:
        yield test_client


def login(client: TestClient) -> None:
    response = client.post(
        "/setup", data={"password": PASSWORD, "confirm": PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 303


def test_first_visit_requires_setup(client) -> None:
    assert client.get("/", follow_redirects=False).headers["location"] == "/setup"
    assert client.get("/api/now").status_code == 401
    assert client.get("/setup").status_code == 200
    mismatch = client.post("/setup", data={"password": PASSWORD, "confirm": "other one"})
    assert "differ" in mismatch.text
    short = client.post("/setup", data={"password": "short", "confirm": "short"})
    assert "at least" in short.text
    login(client)
    assert client.get("/").status_code == 200


def test_login_logout_cycle(client) -> None:
    login(client)
    client.post("/logout")
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert "Wrong password" in client.post("/login", data={"password": "nope nope"}).text
    assert (
        client.post("/login", data={"password": PASSWORD}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/setup", follow_redirects=False).status_code == 303
    assert (
        client.post(
            "/setup", data={"password": "x" * 9, "confirm": "x" * 9}, follow_redirects=False
        ).status_code
        == 303
    )


@pytest.mark.parametrize(
    "path", ["/", "/statistics", "/forecast", "/plan", "/time-of-use", "/settings", "/log"]
)
def test_pages_render(client, path) -> None:
    login(client)
    response = client.get(path)
    assert response.status_code == 200 and "Deye Inverter" in response.text


def test_monitoring_api(client) -> None:
    login(client)
    assert client.get("/api/now").json()["reading"]["battery_soc"] == 60
    assert client.get("/api/history/day?day=2026-10-05").json()["day"] == "2026-10-05"
    assert client.get("/api/statistics?period=month&day=2026-10-05").json()["period"] == "month"
    assert client.get("/api/statistics?period=bogus").status_code == 400
    assert client.get("/api/forecast").json()["days"]
    assert client.get("/static/css/app.css").status_code == 200


def test_plan_api(client) -> None:
    login(client)
    overview = client.get("/api/plan").json()
    assert overview["mode"] == "dry-run" and overview["preview"]["rules"]
    assert client.post("/api/plan/run").json()["trigger"] == "manual"
    assert client.post("/api/plan/mode", json={"mode": "off"}).json() == {"mode": "off"}
    assert client.post("/api/plan/mode", json={"mode": "bogus"}).status_code == 400
    assert client.get("/api/log?kind=decision").json()[0]["kind"] == "decision"


def test_time_of_use_api(client, world) -> None:
    login(client)
    assert client.get("/api/time-of-use").json()["current"][3]["soc"] == 75
    slots = table_to_dicts(winter_table(soc=40))
    assert (
        client.post("/api/time-of-use/base", json={"slots": slots}).json()["base"][0]["soc"] == 40
    )
    sent = client.post("/api/time-of-use/send", json={"slots": slots}).json()
    assert sent["status"] == "executed" and sent["current"][0]["soc"] == 40
    assert client.post("/api/time-of-use/refresh").status_code == 200
    assert client.post("/api/time-of-use/send", json={"slots": slots[:3]}).status_code == 400
    world.gateway.fail = True
    assert client.post("/api/time-of-use/refresh").status_code == 502


def test_settings_api(client) -> None:
    login(client)
    settings = client.get("/api/settings").json()
    settings["reserve"]["max_soc"] = 80
    settings["reserve"]["protect_until"] = "08:00"
    saved = client.post("/api/settings", json=settings).json()
    assert saved["reserve"]["max_soc"] == 80 and saved["reserve"]["protect_until"] == "08:00"
    settings["reserve"]["protect_from"] = "not a time"
    assert client.post("/api/settings", json=settings).status_code == 400


def test_manual_charge_api(client, world) -> None:
    login(client)
    assert client.get("/api/manual-charge").json()["charge"] is None
    body = {"target_soc": 90, "ready_time": None, "hold_until": None}
    assert client.post("/api/manual-charge", json=body).status_code == 409
    client.post("/api/plan/mode", json={"mode": "live"})
    assert client.post("/api/manual-charge", json={**body, "target_soc": 0}).status_code == 400
    started = client.post("/api/manual-charge", json={**body, "hold_until": "18:00"}).json()
    assert started["charge"]["target_soc"] == 90
    assert client.delete("/api/manual-charge").json()["charge"] is None
    client.post("/api/manual-charge", json=body)
    client.post("/api/plan/mode", json={"mode": "off"})
    assert client.get("/api/manual-charge").json()["charge"] is None
    assert client.get("/plan").status_code == 200


def test_static_files_are_revalidated(client) -> None:
    response = client.get("/static/js/manual-charge.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
