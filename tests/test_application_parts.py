"""Each application class built by hand over the repositories, without the container."""

from datetime import date, datetime

from deye_inverter.adapters.clock import SystemClock
from deye_inverter.application.charge_service import SETTING, ChargeSettingsService
from deye_inverter.application.collection import (
    CollectReadings,
    RefreshForecast,
    RefreshInverterSettings,
)
from deye_inverter.application.history_sync import (
    LOCAL,
    BackfillFrames,
    RecordToday,
    SyncDailyEnergy,
    balance_of,
)
from deye_inverter.application.inverter_state import InverterState
from deye_inverter.application.time_of_use_service import (
    TimeOfUseDependencies,
    TimeOfUseService,
)
from tests.conftest import Parts
from tests.fakes import at, reading, winter_table


def test_system_clock_tells_the_time_in_the_site_zone() -> None:
    now = SystemClock("Europe/Bucharest").now()
    assert now.tzinfo is not None and str(now.tzinfo) == "Europe/Bucharest"
    assert abs((datetime.now(now.tzinfo) - now).total_seconds()) < 5


def charging(parts: Parts) -> ChargeSettingsService:
    return ChargeSettingsService(parts.gateway, parts.db.state, parts.db.journal, parts.clock)


def test_grid_charge_switch_is_verified_and_logged(parts: Parts) -> None:
    outcome = charging(parts).set_grid_charge(False)
    assert outcome.status == "executed" and outcome.verified
    settings = parts.db.state.charge_settings()
    assert settings is not None and not settings.grid_charge_enabled
    entry = parts.db.journal.recent(SETTING, 1)[0]
    assert entry["reason"] == "grid charge off"


def test_grid_charge_refused_ignored_and_failing(parts: Parts) -> None:
    parts.gateway.accept = False
    assert charging(parts).set_grid_charge(False).status == "failed"
    parts.gateway.accept = True
    parts.gateway.ignore_writes = True
    assert charging(parts).set_grid_charge(False).status == "mismatch"
    parts.gateway.fail = True
    outcome = charging(parts).set_grid_charge(True)
    assert outcome.status == "failed" and "cloud down" in outcome.message


def test_collection_jobs_copy_the_outside_world(parts: Parts) -> None:
    CollectReadings(parts.gateway, parts.db.readings)()
    assert parts.db.readings.latest() == parts.gateway.live
    RefreshInverterSettings(parts.gateway, parts.db.state, parts.clock)()
    assert parts.db.state.current_table() == parts.gateway.table
    assert parts.db.state.battery_settings() == parts.gateway.read_battery_settings()
    RefreshForecast(parts.provider, parts.db.forecasts, parts.db.settings, parts.clock)()
    assert parts.provider.sites == [parts.db.settings.load().site]
    assert parts.db.forecasts.load(at(0), at(23)).hours


def test_record_today_waits_for_a_reading_then_saves_its_counters(parts: Parts) -> None:
    record = RecordToday(parts.db.readings, parts.db.daily, parts.clock)
    record()
    assert parts.db.daily.first_day() is None
    live = reading(at(9), solar_today=4.5)
    parts.db.readings.add(live)
    record()
    saved = parts.db.daily.between(date(2026, 10, 5), date(2026, 10, 5))
    assert [(day.balance, day.source) for day in saved] == [(balance_of(live), LOCAL)]


def test_daily_sync_copies_all_history_once_then_the_last_month(parts: Parts) -> None:
    sync = SyncDailyEnergy(parts.history, parts.db.daily, parts.clock)
    sync()
    assert parts.history.daily_calls == [(date(2026, 10, 1), date(2026, 10, 4))]
    sync()
    assert parts.history.daily_calls[-1] == (date(2026, 10, 1), date(2026, 10, 4))
    assert parts.db.daily.first_day() == date(2026, 10, 1)


def test_backfill_retries_a_refused_day_a_limited_number_of_times(parts: Parts) -> None:
    parts.history.failing = {date(2026, 10, 4)}
    backfill = BackfillFrames(parts.history, parts.db.readings, parts.clock)
    for _ in range(BackfillFrames.MAX_ATTEMPTS):
        assert backfill() == {"filled": 0, "remaining": 4}
    assert backfill() == {"filled": 3, "remaining": 0}
    assert parts.history.frame_calls.count(date(2026, 10, 4)) == BackfillFrames.MAX_ATTEMPTS


def test_inverter_state_is_empty_until_read_and_the_first_table_is_the_base(parts: Parts) -> None:
    state = InverterState(parts.db.store)
    assert state.current_table() is None and state.base_table() is None
    assert state.charge_settings_read_at() is None
    state.remember_current_table(winter_table(soc=40), at(9))
    state.remember_current_table(winter_table(soc=60), at(10))
    assert state.current_table() == winter_table(soc=60)
    assert state.base_table() == winter_table(soc=40)
    assert state.current_table_read_at() == at(10).isoformat()


def test_time_of_use_service_rereads_until_the_cloud_shows_the_new_table(parts: Parts) -> None:
    pauses: list[float] = []
    deps = TimeOfUseDependencies(
        parts.gateway,
        parts.db.state,
        parts.db.journal,
        parts.clock,
        parts.db.settings,
        pauses.append,
    )
    parts.gateway.stale_reads = 1
    outcome = TimeOfUseService(deps).send(winter_table(soc=40), "test")
    assert outcome.status == "executed" and len(pauses) == 1
