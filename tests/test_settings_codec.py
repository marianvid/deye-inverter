from datetime import date, time

from deye_inverter.domain.settings import (
    Mode,
    PlannerSettings,
    ReserveSettings,
    SettingsCodec,
    TuningSettings,
)


def test_round_trip_keeps_every_value() -> None:
    codec = SettingsCodec()
    settings = PlannerSettings(
        mode=Mode.LIVE,
        reserve=ReserveSettings(skip_dates=(date(2026, 12, 25),), protect_from=time(15, 30)),
        tuning=TuningSettings(charge_margin=1.1),
    )
    assert codec.from_dict(codec.to_dict(settings)) == settings


def test_partial_and_old_data_fall_back_to_defaults() -> None:
    settings = SettingsCodec().from_dict(
        {
            "reserve": {"max_soc": "80", "target_soc": 75},  # target_soc: an old field
            "site": {"panel_kwp": 7},
            "morning": {"target_soc": 55},  # an old section
        }
    )
    assert settings.reserve.max_soc == 80
    assert settings.site.panel_kwp == 7.0
    assert settings.mode is Mode.DRY_RUN
    assert settings.floor.soc == 30
    assert settings.tuning == TuningSettings()


def test_encoded_form_is_plain_json() -> None:
    data = SettingsCodec().to_dict(PlannerSettings())
    assert data["reserve"]["protect_from"] == "16:00"
    assert data["reserve"]["protect_until"] == "09:00"
    assert data["reserve"]["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert data["mode"] == "dry-run"
    assert data["tuning"]["charge_margin"] == 1.2


def test_configured_site_is_the_default_until_edited() -> None:
    from deye_inverter.domain.settings import SiteSettings

    codec = SettingsCodec(PlannerSettings(site=SiteSettings(latitude=1.5, longitude=2.5)))
    assert codec.from_dict({}).site.latitude == 1.5
    assert codec.from_dict({"site": {"latitude": 3}}).site.latitude == 3.0
    assert PlannerSettings().site.latitude == 0.0
