from datetime import date

import pytest

from deye_inverter.application.energy_model import EnergyModel, today_solar
from deye_inverter.application.views import hourly_energy
from deye_inverter.domain.readings import BatterySettings, ChargeSettings
from deye_inverter.domain.settings import SiteSettings, TuningSettings
from tests.fakes import ZONE, at, flat_forecast, reading

TUNING = TuningSettings()


def test_views_after_collection(world, primed) -> None:
    primed()
    now = world.services.views.now()
    assert now["reading"]["battery_soc"] == 60
    assert now["age_seconds"] == 3600
    assert now["battery_settings"]["max_charge_current"] == 100
    series = world.services.views.day_series(date(2026, 10, 5))
    assert series["times"] == ["09:00"]
    world.services.record_today()
    forecast = world.services.views.forecast()
    assert len(forecast["days"]) == 4 and forecast["hours"]
    assert forecast["days"][1]["actual_kwh"] == 0.0
    assert now["charge_settings"]["grid_charge_current"] == 60
    tou = world.services.views.time_of_use()
    assert tou["current"] == tou["base"]


def test_empty_views(world) -> None:
    assert world.services.views.now() == {
        "reading": None,
        "age_seconds": None,
        "battery_settings": None,
        "charge_settings": None,
    }
    assert world.services.views.time_of_use()["current"] is None


def test_hourly_energy_from_mean_power() -> None:
    readings = [reading(at(9, 30)), reading(at(9, 55)), reading(at(10, 20))]
    hours = hourly_energy(readings, ZONE)
    assert [h["solar_kwh"] for h in hours] == [1.0, 1.0]


def test_energy_model(world) -> None:
    model = EnergyModel(world.services.views._readings)
    forecast = flat_forecast(at(6), 10, 1.0)
    assert model.solar_ratio(at(6, 10), forecast, 0.0, TUNING) == 1.0
    assert model.solar_ratio(at(10), forecast, 2.0, TUNING) == 0.5
    assert model.solar_ratio(at(10), forecast, 40.0, TUNING) == 1.5
    site = SiteSettings(consumption_days=2)
    assert model.load_profile(at(10), site).hourly_kw == (site.fallback_load_kw,) * 24
    repository = world.services.views._readings
    repository.add(reading(at(8, day=4), load_power=1200))
    repository.add(reading(at(8, 30, day=4), load_power=600))
    repository.add(reading(at(20, day=4), load_power=300))
    profile = model.load_profile(at(10), site)
    assert profile.hourly_kw[8] == pytest.approx(0.9)
    assert profile.hourly_kw[20] == pytest.approx(0.3)
    assert profile.hourly_kw[3] == pytest.approx(0.6)
    assert model.grid_charge_kw(None, None, SiteSettings(), TUNING) == 3.0
    battery = BatterySettings(100, 20, 30, 315)
    charge = ChargeSettings(True, 60, True, "Zero export to CT", 100, 190)
    assert model.grid_charge_kw(battery, None, SiteSettings(), TUNING) == pytest.approx(5.12)
    assert model.grid_charge_kw(battery, charge, SiteSettings(), TUNING) == pytest.approx(3.072)
    assert today_solar(None, at(10)) == 0.0
    assert today_solar(reading(at(9, day=4), solar_today=5), at(10)) == 0.0
    assert today_solar(reading(at(9), solar_today=5), at(10)) == 5
