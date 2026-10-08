"""Solar forecast: expected energy per hour on the panel plane."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class ForecastHour:
    """Expected solar energy in the hour that *ends* at ``hour_end``."""

    hour_end: datetime
    irradiance: float
    solar_kwh: float

    @property
    def hour_start(self) -> datetime:
        return self.hour_end - HOUR


@dataclass(frozen=True)
class Forecast:
    hours: tuple[ForecastHour, ...]

    @classmethod
    def of(cls, hours: Iterable[ForecastHour]) -> Forecast:
        return cls(tuple(sorted(hours, key=lambda h: h.hour_end)))

    def energy_between(self, start: datetime, end: datetime) -> float:
        """Solar energy expected between two moments, pro rata for partial hours."""
        total = 0.0
        for hour in self.hours:
            overlap = min(end, hour.hour_end) - max(start, hour.hour_start)
            if overlap > timedelta(0):
                total += hour.solar_kwh * (overlap / HOUR)
        return total

    def energy_on(self, day: date) -> float:
        return sum(h.solar_kwh for h in self.hours if h.hour_start.date() == day)

    def is_empty(self) -> bool:
        return not self.hours
