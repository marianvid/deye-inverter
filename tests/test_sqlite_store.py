from datetime import date, timedelta

from deye_inverter.adapters.sqlite_store import (
    Database,
    SqliteDailyEnergyRepository,
    SqliteForecastRepository,
    SqliteJournalRepository,
    SqliteKeyValueStore,
    SqliteReadingRepository,
    SqliteSettingsRepository,
)
from deye_inverter.domain.energy import DailyEnergy, EnergyBalance
from deye_inverter.domain.settings import Mode, PlannerSettings
from tests.fakes import ZONE, at, flat_forecast, reading


def test_readings_round_trip_and_samples_per_day(tmp_path) -> None:
    repo = SqliteReadingRepository(Database(tmp_path / "sub" / "deye.db"), ZONE)
    assert repo.latest() is None
    for hour, solar in ((9, 1.0), (12, 4.0), (15, 7.5)):
        repo.add(reading(at(hour), solar_today=solar))
    repo.add(reading(at(10, day=6), solar_today=2.0))
    latest = repo.latest()
    assert latest is not None and latest.solar_today == 2.0 and latest.raw == {"SOC": "60"}
    assert len(repo.between(at(0), at(23, 59))) == 3
    counts = repo.samples_per_day(date(2026, 10, 5), date(2026, 10, 6))
    assert counts == {date(2026, 10, 5): 3, date(2026, 10, 6): 1}


def test_forecast_save_and_load() -> None:
    repo = SqliteForecastRepository(Database(":memory:"))
    repo.save(flat_forecast(at(8), 4, 1.5), at(7))
    loaded = repo.load(at(8), at(10))
    assert [h.solar_kwh for h in loaded.hours] == [1.5, 1.5]
    assert loaded.hours[0].hour_end == at(9)


def test_settings_default_and_saved() -> None:
    store = SqliteKeyValueStore(Database(":memory:"))
    repo = SqliteSettingsRepository(store)
    assert repo.load() == PlannerSettings()
    repo.save(PlannerSettings(mode=Mode.OFF))
    assert repo.load().mode is Mode.OFF
    assert store.get("missing") is None


def test_journal_recent_and_count() -> None:
    journal = SqliteJournalRepository(Database(":memory:"))
    journal.add("command", at(10), {"status": "executed"})
    journal.add("command", at(11), {"status": "failed"})
    journal.add("decision", at(12), {"status": "dry-run"})
    assert [e["status"] for e in journal.recent(None, 10)] == ["dry-run", "failed", "executed"]
    assert len(journal.recent("command", 10)) == 2
    assert journal.count_since("command", at(0), "executed") == 1
    assert journal.count_since("command", at(10) + timedelta(minutes=1), "executed") == 0


def test_daily_energy_upsert_and_range() -> None:
    repo = SqliteDailyEnergyRepository(Database(":memory:"))
    assert repo.first_day() is None
    repo.save(DailyEnergy(date(2026, 10, 2), EnergyBalance(10, 8, 2, 3, 3), "cloud"))
    repo.save(DailyEnergy(date(2026, 10, 1), EnergyBalance(5, 6, 1, 1, 1), "cloud"))
    repo.save(DailyEnergy(date(2026, 10, 2), EnergyBalance(11, 8, 2, 3, 3), "local"))
    records = repo.between(date(2026, 10, 1), date(2026, 10, 31))
    assert [(r.day.day, r.balance.solar, r.source) for r in records] == [
        (1, 5, "cloud"),
        (2, 11, "local"),
    ]
    assert repo.first_day() == date(2026, 10, 1)
