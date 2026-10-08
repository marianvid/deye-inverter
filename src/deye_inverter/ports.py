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
    accepted: bool
    order_id: str
    status: str
    message: str


class InverterGateway(ABC):
    @abstractmethod
    def read_live(self) -> Reading: ...

    @abstractmethod
    def read_time_of_use(self) -> TimeOfUseTable: ...

    @abstractmethod
    def read_battery_settings(self) -> BatterySettings: ...

    @abstractmethod
    def read_charge_settings(self) -> ChargeSettings: ...

    @abstractmethod
    def write_time_of_use(self, table: TimeOfUseTable) -> WriteResult: ...

    @abstractmethod
    def set_grid_charge(self, enabled: bool) -> WriteResult: ...


class ForecastProvider(ABC):
    @abstractmethod
    def fetch(self, site: SiteSettings) -> Forecast: ...


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...


class ReadingRepository(ABC):
    @abstractmethod
    def add(self, reading: Reading) -> None: ...

    @abstractmethod
    def latest(self) -> Reading | None: ...

    @abstractmethod
    def between(self, start: datetime, end: datetime) -> list[Reading]: ...

    @abstractmethod
    def add_many(self, readings: list[Reading]) -> None: ...

    @abstractmethod
    def samples_per_day(self, start: date, end: date) -> dict[date, int]: ...


class DailyEnergyRepository(ABC):
    @abstractmethod
    def save(self, record: DailyEnergy) -> None: ...

    @abstractmethod
    def between(self, start: date, end: date) -> list[DailyEnergy]: ...

    @abstractmethod
    def first_day(self) -> date | None: ...


class EnergyHistorySource(ABC):
    """History kept by the inverter's cloud: daily energies and 5-minute power frames."""

    @abstractmethod
    def first_day(self) -> date: ...

    @abstractmethod
    def daily(self, start: date, end: date) -> list[DailyEnergy]: ...

    @abstractmethod
    def frames(self, day: date) -> list[Reading]: ...


class ForecastRepository(ABC):
    @abstractmethod
    def save(self, forecast: Forecast, fetched_at: datetime) -> None: ...

    @abstractmethod
    def load(self, start: datetime, end: datetime) -> Forecast: ...


class SettingsRepository(ABC):
    codec: SettingsCodec

    @abstractmethod
    def load(self) -> PlannerSettings: ...

    @abstractmethod
    def save(self, settings: PlannerSettings) -> None: ...


class KeyValueStore(ABC):
    """Small named values: password hash, session secret, base table, last tables."""

    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def put(self, key: str, value: str) -> None: ...


class JournalRepository(ABC):
    """Planner decisions and commands sent to the inverter."""

    @abstractmethod
    def add(self, kind: str, at: datetime, entry: dict[str, Any]) -> None: ...

    @abstractmethod
    def recent(self, kind: str | None, limit: int) -> list[dict[str, Any]]: ...

    @abstractmethod
    def count_since(self, kind: str, since: datetime, status: str) -> int: ...
