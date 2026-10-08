"""Estimates the planner needs, derived from local history."""

from __future__ import annotations

from datetime import datetime, timedelta

from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.load import HOURS_PER_DAY, LoadProfile
from deye_inverter.domain.readings import BatterySettings, ChargeSettings, Reading
from deye_inverter.domain.settings import SiteSettings, TuningSettings
from deye_inverter.ports import ReadingRepository


class EnergyModel:
    def __init__(self, readings: ReadingRepository) -> None:
        self._readings = readings

    def solar_ratio(
        self, now: datetime, forecast: Forecast, today_solar_kwh: float, tuning: TuningSettings
    ) -> float:
        """Actual ÷ forecast solar energy so far today, bounded; 1.0 when too early to tell."""
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        expected = forecast.energy_between(midnight, now)
        if expected < tuning.min_forecast_for_ratio_kwh:
            return 1.0
        ratio = today_solar_kwh / expected
        return max(tuning.solar_ratio_min, min(tuning.solar_ratio_max, ratio))

    def load_profile(self, now: datetime, site: SiteSettings) -> LoadProfile:
        """Average house load per clock hour over the last ``consumption_days`` days.

        Hours without history take the average of the others, or the fallback load.
        """
        sums = [0.0] * HOURS_PER_DAY
        counts = [0] * HOURS_PER_DAY
        start = now - timedelta(days=site.consumption_days)
        for reading in self._readings.between(start, now):
            hour = reading.taken_at.astimezone(now.tzinfo).hour
            sums[hour] += reading.load_power
            counts[hour] += 1
        known = [sums[h] / counts[h] / 1000 for h in range(HOURS_PER_DAY) if counts[h]]
        default = sum(known) / len(known) if known else site.fallback_load_kw
        return LoadProfile(
            tuple(
                sums[h] / counts[h] / 1000 if counts[h] else default for h in range(HOURS_PER_DAY)
            )
        )

    @staticmethod
    def grid_charge_kw(
        battery: BatterySettings | None,
        charge: ChargeSettings | None,
        site: SiteSettings,
        tuning: TuningSettings,
    ) -> float:
        """Charging power from the grid that the inverter's own settings allow."""
        limits = [battery.max_charge_current] if battery else []
        if charge is not None:
            limits.append(charge.grid_charge_current)
        amps = min((a for a in limits if a > 0), default=0)
        if amps <= 0:
            return tuning.fallback_charge_kw
        return amps * site.battery_nominal_voltage / 1000


def today_solar(latest: Reading | None, now: datetime) -> float:
    if latest is None or latest.taken_at.astimezone(now.tzinfo).date() != now.date():
        return 0.0
    return latest.solar_today
