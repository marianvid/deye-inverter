from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from deye_inverter.application.profiles import ProfileError, ProfilesLockedError
from deye_inverter.domain.settings import Mode
from deye_inverter.domain.time_of_use import table_to_dicts
from deye_inverter.web.app import create_app
from tests.fakes import winter_table


def set_mode(world, mode: Mode) -> None:
    world.services.settings.save(replace(world.services.settings.load(), mode=mode))


def test_save_replace_delete(world) -> None:
    profiles = world.services.profiles
    assert profiles.all() == []
    profiles.save(" winter ", winter_table())
    profiles.save("Summer", winter_table(soc=30))
    profiles.save("winter", winter_table(soc=40))
    assert [p.name for p in profiles.all()] == ["Summer", "winter"]
    assert profiles.all()[1].table.slots[0].soc == 40
    assert [p.name for p in profiles.delete("Summer")] == ["winter"]
    with pytest.raises(ProfileError):
        profiles.save("   ", winter_table())


def test_apply_only_when_automation_is_off(world) -> None:
    profiles = world.services.profiles
    profiles.save("cheap night", winter_table(soc=30))
    with pytest.raises(ProfilesLockedError):
        profiles.apply("cheap night")
    set_mode(world, Mode.OFF)
    outcome = profiles.apply("cheap night")
    assert outcome.status == "executed"
    assert world.gateway.table == winter_table(soc=30)
    assert world.services.journal.recent("command", 1)[0]["reason"] == "profile cheap night"
    with pytest.raises(ProfileError):
        profiles.apply("missing")


@pytest.fixture
def logged_in(world, primed):
    primed()
    with TestClient(create_app(world.services)) as client:
        client.post("/setup", data={"password": "correct horse", "confirm": "correct horse"})
        yield client


def test_profiles_api(logged_in, world) -> None:
    client = logged_in
    slots = table_to_dicts(winter_table(soc=30))
    shown = client.post("/api/time-of-use/profiles", json={"name": "night", "slots": slots}).json()
    assert shown["mode"] == "dry-run" and shown["profiles"][0]["name"] == "night"
    assert (
        client.post("/api/time-of-use/profiles", json={"name": "", "slots": slots}).status_code
        == 400
    )
    assert client.post("/api/time-of-use/profiles/night/apply").status_code == 409
    set_mode(world, Mode.OFF)
    applied = client.post("/api/time-of-use/profiles/night/apply").json()
    assert applied["status"] == "executed" and applied["current"][0]["soc"] == 30
    assert client.post("/api/time-of-use/profiles/none/apply").status_code == 404
    assert client.delete("/api/time-of-use/profiles/night").json()["profiles"] == []
    tou = client.get("/api/time-of-use").json()
    assert tou["charge_settings"]["grid_charge_enabled"] is True


def test_grid_charge_switch(world) -> None:
    charging = world.services.charging
    outcome = charging.set_grid_charge(False)
    assert outcome.status == "executed" and world.gateway.grid_charge is False
    assert world.services.state.charge_settings().grid_charge_enabled is False
    assert world.services.journal.recent("setting", 1)[0]["reason"] == "grid charge off"
    world.gateway.ignore_writes = True
    assert charging.set_grid_charge(True).status == "mismatch"
    world.gateway.accept = False
    assert charging.set_grid_charge(True).status == "failed"
    world.gateway.fail = True
    assert "cloud down" in charging.set_grid_charge(True).message


def test_grid_charge_api(logged_in, world) -> None:
    answer = logged_in.post("/api/charge-settings/grid-charge", json={"enabled": False}).json()
    assert answer["status"] == "executed"
    assert answer["charge_settings"]["grid_charge_enabled"] is False
