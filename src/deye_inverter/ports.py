"""Interfaces between the application and the outside world (ports).

The application depends only on these; adapters implement them. A new data
source (for example RS485/Modbus) implements :class:`InverterGateway`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from deye_inverter.domain.energy import DailyEnergy
from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.readings import BatterySettings, ChargeSettings, Reading
from deye_inverter.domain.settings import PlannerSettings, SettingsCodec, SiteSettings
from deye_inverter.domain.time_of_use import TimeOfUseTable


class GatewayError(Exception):
    """The inverter could not be reached or refused a request."""


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a command sent to the inverter: accepted or not, its order id and status."""

    accepted: bool
    order_id: str
    status: str
    message: str


class InverterGateway(ABC):
    """Access to the inverter: live readings, its settings, and commands that change them."""

    @abstractmethod
    def read_live(self) -> Reading:
        """Must return the inverter's latest reading (powers, battery SOC, daily energies)."""

    @abstractmethod
    def read_time_of_use(self) -> TimeOfUseTable:
        """Must return the time-of-use table currently configured on the inverter."""

    @abstractmethod
    def read_battery_settings(self) -> BatterySettings:
        """Must return the battery config: max charge current, shutdown and low SOC, capacity."""

    @abstractmethod
    def read_charge_settings(self) -> ChargeSettings:
        """Must return grid charge switch and current, work mode, time-of-use flag, limits."""

    @abstractmethod
    def write_time_of_use(self, table: TimeOfUseTable) -> WriteResult:
        """Must send the time-of-use table to the inverter and report whether it was applied."""

    @abstractmethod
    def set_grid_charge(self, enabled: bool) -> WriteResult:
        """Must switch battery charging from the grid on or off and report the outcome."""


class ForecastProvider(ABC):
    """Source of solar forecasts for the site."""

    @abstractmethod
    def fetch(self, site: SiteSettings) -> Forecast:
        """Must return the hourly irradiance and solar energy forecast for the site's panels."""


class Clock(ABC):
    """Source of the current time, replaceable in tests."""

    @abstractmethod
    def now(self) -> datetime:
        """Must return the current time as an aware datetime in the site's time zone."""


class ReadingRepository(ABC):
    """Storage of inverter readings over time."""

    @abstractmethod
    def add(self, reading: Reading) -> None:
        """Must store one reading, replacing any reading taken at the same moment."""

    @abstractmethod
    def latest(self) -> Reading | None:
        """Must return the most recent stored reading, or None when there is none."""

    @abstractmethod
    def between(self, start: datetime, end: datetime) -> list[Reading]:
        """Must return readings taken from ``start`` up to, not including, ``end``, oldest first."""

    @abstractmethod
    def add_many(self, readings: list[Reading]) -> None:
        """Must store all readings at once, replacing any taken at the same moments."""

    @abstractmethod
    def samples_per_day(self, start: date, end: date) -> dict[date, int]:
        """Must count stored readings per local day from ``start`` to ``end``, both inclusive."""


class DailyEnergyRepository(ABC):
    """Storage of daily energy totals: solar, consumption, bought, charged, discharged."""

    @abstractmethod
    def save(self, record: DailyEnergy) -> None:
        """Must store one day's energy record, replacing an earlier record for that day."""

    @abstractmethod
    def between(self, start: date, end: date) -> list[DailyEnergy]:
        """Must return the records from ``start`` to ``end``, both inclusive, ordered by day."""

    @abstractmethod
    def first_day(self) -> date | None:
        """Must return the earliest day with a stored record, or None when there is none."""


class EnergyHistorySource(ABC):
    """History kept by the inverter's cloud: daily energies and 5-minute power frames."""

    @abstractmethod
    def first_day(self) -> date:
        """Must return the day the station started operating, as the cloud reports it."""

    @abstractmethod
    def daily(self, start: date, end: date) -> list[DailyEnergy]:
        """Must return the daily energy balances from ``start`` to ``end``, both inclusive."""

    @abstractmethod
    def frames(self, day: date) -> list[Reading]:
        """Must return the day's 5-minute power frames (powers and battery SOC) as readings."""


class ForecastRepository(ABC):
    """Storage of fetched hourly solar forecasts."""

    @abstractmethod
    def save(self, forecast: Forecast, fetched_at: datetime) -> None:
        """Must store each forecast hour with its fetch time, overwriting older values."""

    @abstractmethod
    def load(self, start: datetime, end: datetime) -> Forecast:
        """Must return the stored forecast hours ending after ``start`` and up to ``end``."""


class SettingsRepository(ABC):
    """Storage of the planner settings, with the codec that converts them to and from dicts."""

    codec: SettingsCodec

    @abstractmethod
    def load(self) -> PlannerSettings:
        """Must return the saved planner settings, or the defaults when none are saved."""

    @abstractmethod
    def save(self, settings: PlannerSettings) -> None:
        """Must persist the planner settings, replacing the previous ones."""


class KeyValueStore(ABC):
    """Small named values: password hash, session secret, base table, last tables."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Must return the value stored under ``key``, or None when it was never set."""

    @abstractmethod
    def put(self, key: str, value: str) -> None:
        """Must store ``value`` under ``key``, replacing any previous value."""


class JournalRepository(ABC):
    """Planner decisions and commands sent to the inverter."""

    @abstractmethod
    def add(self, kind: str, at: datetime, entry: dict[str, Any]) -> None:
        """Must append an entry of the given kind (decision or command) recorded at ``at``."""

    @abstractmethod
    def recent(self, kind: str | None, limit: int) -> list[dict[str, Any]]:
        """Must return up to ``limit`` newest entries, of one kind or all kinds, newest first."""

    @abstractmethod
    def count_since(self, kind: str, since: datetime, status: str) -> int:
        """Must count entries of ``kind`` with ``status`` recorded at or after ``since``."""
