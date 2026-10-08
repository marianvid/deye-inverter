"""What a grid outage would need: an hour-by-hour simulation.

For a moment T the required SOC is the lowest SOC with which the house, on its
essential load only, gets from T through the night until the trusted part of the
sun covers that load again, without the battery going below its shutdown level.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.load import LoadProfile
from deye_inverter.domain.settings import ReserveSettings

STEP = timedelta(hours=1)
# The simulation never looks further ahead than this (no sun at all: reserve = max).
LONGEST_OUTAGE = timedelta(hours=36)
# Below this the forecast hour counts as dark (night).
DARK_KWH = 0.01


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def _within(moment: datetime, start: time, end: time) -> bool:
    minute = moment.hour * 60 + moment.minute
    low, high = _minutes(start), _minutes(end)
    return low <= minute < high if low <= high else minute >= low or minute < high


@dataclass(frozen=True)
class OutageLoad:
    """Essential house load (kW) during an outage, by clock time."""

    settings: ReserveSettings
    profile: LoadProfile

    def kw(self, moment: datetime) -> float:
        s = self.settings
        if _within(moment, s.protect_from, s.evening_until):
            return s.evening_kw
        if _within(moment, s.evening_until, s.late_evening_until):
            return s.late_evening_kw
        if _within(moment, s.morning_from, s.morning_until):
            return s.morning_kw
        return min(self.profile.hourly_kw[moment.hour] * s.night_margin, s.night_cap_kw)


@dataclass(frozen=True)
class OutageSimulation:
    settings: ReserveSettings
    load: OutageLoad
    forecast: Forecast
    battery_kwh: float
    shutdown_soc: int

    def required_at(self, start: datetime) -> int:
        """Lowest SOC at ``start`` that carries an outage through, capped at ``max_soc``."""
        cap = max(self.shutdown_soc, min(100, self.settings.max_soc))
        if not self._survives(start, cap):
            return cap
        low, high = self.shutdown_soc, cap  # surviving only gets easier with more SOC
        while low < high:
            middle = (low + high) // 2
            if self._survives(start, middle):
                high = middle
            else:
                low = middle + 1
        return low

    def _survives(self, start: datetime, soc: float) -> bool:
        end = start + self._longest()
        night_passed = start.hour < 12  # an outage after midnight is already in the night
        moment = start
        while moment < end:
            forecast = self.forecast.energy_between(moment, moment + STEP)
            solar = forecast * self.settings.solar_factor
            load = self.load.kw(moment)
            if night_passed and solar >= load:
                return True  # morning: the panels carry the house again
            night_passed = night_passed or forecast < DARK_KWH
            soc = min(100.0, soc + (solar - load) / self.battery_kwh * 100)
            if soc < self.shutdown_soc:
                return False
            moment += STEP
        return True

    def _longest(self) -> timedelta:
        if self.settings.generator_available:
            return timedelta(hours=self.settings.generator_bridge_hours)
        return LONGEST_OUTAGE
