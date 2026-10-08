"""Jobs that keep the daily energy table and the power history complete."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from deye_inverter.domain.energy import DailyEnergy, EnergyBalance
from deye_inverter.domain.readings import Reading
from deye_inverter.ports import (
    Clock,
    DailyEnergyRepository,
    EnergyHistorySource,
    GatewayError,
    ReadingRepository,
)

LOCAL = "local"
RECENT_DAYS = 31
# A day with fewer samples than this (of 288 five-minute slots) is filled from the cloud.
COMPLETE_DAY_SAMPLES = 250


def balance_of(reading: Reading) -> EnergyBalance:
    """The inverter's day counters as an energy balance."""
    return EnergyBalance(
        solar=reading.solar_today,
        consumption=reading.load_today,
        bought=reading.grid_bought_today,
        charged=reading.battery_charged_today,
        discharged=reading.battery_discharged_today,
    )


class RecordToday:
    """Writes today's running totals from the latest live reading."""

    def __init__(
        self, readings: ReadingRepository, daily: DailyEnergyRepository, clock: Clock
    ) -> None:
        self._readings = readings
        self._daily = daily
        self._clock = clock

    def __call__(self) -> None:
        latest = self._readings.latest()
        if latest is None:
            return
        day = latest.taken_at.astimezone(self._clock.now().tzinfo).date()
        self._daily.save(DailyEnergy(day, balance_of(latest), LOCAL))


class SyncDailyEnergy:
    """Copies finished days from the cloud: the whole history once, then the last month."""

    def __init__(
        self, source: EnergyHistorySource, daily: DailyEnergyRepository, clock: Clock
    ) -> None:
        self._source = source
        self._daily = daily
        self._clock = clock

    def __call__(self) -> None:
        yesterday = self._clock.now().date() - timedelta(days=1)
        have = self._daily.first_day()
        start = self._source.first_day()
        if have is not None and have <= start:
            start = max(start, yesterday - timedelta(days=RECENT_DAYS - 1))
        if start > yesterday:
            return
        for record in self._source.daily(start, yesterday):
            self._daily.save(record)


class BackfillFrames:
    """Fills the power history of days the collector did not see, a few days per run.

    A day the cloud refuses is retried on later runs, up to ``MAX_ATTEMPTS`` times.
    """

    MAX_ATTEMPTS = 3

    def __init__(
        self,
        source: EnergyHistorySource,
        readings: ReadingRepository,
        clock: Clock,
        days_per_run: int = 6,
    ) -> None:
        self._source = source
        self._readings = readings
        self._clock = clock
        self._days_per_run = days_per_run
        self._attempts: dict[date, int] = {}
        self._fetched: set[date] = set()

    def __call__(self) -> dict[str, Any]:
        missing = [day for day in self._missing_days() if self._eligible(day)]
        filled = 0
        for day in missing[: self._days_per_run]:
            self._attempts[day] = self._attempts.get(day, 0) + 1
            try:
                self._readings.add_many(self._source.frames(day))
            except GatewayError:
                break
            self._fetched.add(day)
            filled += 1
        return {"filled": filled, "remaining": len(missing) - filled}

    def _eligible(self, day: date) -> bool:
        return day not in self._fetched and self._attempts.get(day, 0) < self.MAX_ATTEMPTS

    def _missing_days(self) -> list[date]:
        first = self._source.first_day()
        yesterday = self._clock.now().date() - timedelta(days=1)
        counts = self._readings.samples_per_day(first, yesterday)
        days = (first + timedelta(days=i) for i in range((yesterday - first).days + 1))
        incomplete = (day for day in days if counts.get(day, 0) < COMPLETE_DAY_SAMPLES)
        return sorted(incomplete, reverse=True)
