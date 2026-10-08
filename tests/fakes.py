"""Test doubles for the ports."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from deye_inverter.domain.energy import DailyEnergy, EnergyBalance
from deye_inverter.domain.forecast import Forecast, ForecastHour
from deye_inverter.domain.readings import BatterySettings, ChargeSettings, Reading
from deye_inverter.domain.settings import SiteSettings
from deye_inverter.domain.time_of_use import TimeOfUseSlot, TimeOfUseTable
from deye_inverter.ports import (
    Clock,
    EnergyHistorySource,
    ForecastProvider,
    GatewayError,
    InverterGateway,
    WriteResult,
)

ZONE = ZoneInfo("Europe/Bucharest")


def at(hour: int, minute: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZONE)


def winter_table(soc: int = 55, grid_charge: bool = True) -> TimeOfUseTable:
    starts = [1, 5, 9, 13, 17, 21]
    return TimeOfUseTable(
        tuple(
            TimeOfUseSlot(time(h, 0), 75 if h == 13 else soc, 8000, 50.0, grid_charge, False)
            for h in starts
        )
    )


def reading(
    taken_at: datetime, soc: float = 60, solar_today: float = 0.0, load_power: float = 600
) -> Reading:
    return Reading(
        taken_at=taken_at,
        solar_power=1000,
        load_power=load_power,
        backup_load_power=300,
        grid_power=20,
        battery_power=-100,
        battery_soc=soc,
        battery_voltage=52.0,
        solar_today=solar_today,
        load_today=5.0,
        grid_bought_today=0.2,
        battery_charged_today=2.0,
        battery_discharged_today=1.0,
        battery_temperature=25.0,
        raw={"SOC": str(soc)},
    )


def flat_forecast(start: datetime, hours: int, kwh_per_hour: float) -> Forecast:
    return Forecast.of(
        ForecastHour(start + timedelta(hours=i + 1), kwh_per_hour * 125, kwh_per_hour)
        for i in range(hours)
    )


class FixedClock(Clock):
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class FakeGateway(InverterGateway):
    def __init__(self, table: TimeOfUseTable | None = None) -> None:
        self.table = table or winter_table()
        self.written: list[TimeOfUseTable] = []
        self.accept = True
        self.fail = False
        self.ignore_writes = False
        self.live = reading(at(9))
        self.grid_charge = True
        self.stale_reads = 0  # reads that still show the table before the last write
        self._previous = self.table

    def read_live(self) -> Reading:
        if self.fail:
            raise GatewayError("cloud down")
        return self.live

    def read_time_of_use(self) -> TimeOfUseTable:
        if self.fail:
            raise GatewayError("cloud down")
        if self.stale_reads > 0:
            self.stale_reads -= 1
            return self._previous
        return self.table

    def read_battery_settings(self) -> BatterySettings:
        return BatterySettings(100, 20, 30, 315)

    def read_charge_settings(self) -> ChargeSettings:
        return ChargeSettings(self.grid_charge, 60, True, "Zero export to CT", 100, 190)

    def set_grid_charge(self, enabled: bool) -> WriteResult:
        if self.fail:
            raise GatewayError("cloud down")
        if self.accept and not self.ignore_writes:
            self.grid_charge = enabled
        return WriteResult(self.accept, "43", "666" if self.accept else "500", "done")

    def write_time_of_use(self, table: TimeOfUseTable) -> WriteResult:
        if self.fail:
            raise GatewayError("cloud down")
        self.written.append(table)
        self._previous = self.table
        if self.accept and not self.ignore_writes:
            self.table = table
        return WriteResult(self.accept, "42", "666" if self.accept else "500", "done")


class FakeForecastProvider(ForecastProvider):
    def __init__(self, forecast: Forecast) -> None:
        self.forecast = forecast
        self.sites: list[SiteSettings] = []

    def fetch(self, site: SiteSettings) -> Forecast:
        self.sites.append(site)
        return self.forecast


class FakeHistory(EnergyHistorySource):
    """Cloud history from 2026-10-01: 10 kWh solar, 8 consumed, 2 bought per day."""

    def __init__(self, first: date = date(2026, 10, 1)) -> None:
        self.first = first
        self.daily_calls: list[tuple[date, date]] = []
        self.frame_calls: list[date] = []
        self.failing: set[date] = set()

    def first_day(self) -> date:
        return self.first

    def daily(self, start: date, end: date) -> list[DailyEnergy]:
        self.daily_calls.append((start, end))
        days = (start + timedelta(days=i) for i in range((end - start).days + 1))
        return [DailyEnergy(d, EnergyBalance(10, 8, 2, 3, 3), "cloud") for d in days]

    def frames(self, day: date) -> list[Reading]:
        self.frame_calls.append(day)
        if day in self.failing:
            raise GatewayError("HTTP 500")
        start = datetime.combine(day, time(0, 0), tzinfo=ZONE)
        return [reading(start + timedelta(minutes=5 * i), soc=50) for i in range(12)]
