"""Read models for the interface: plain dictionaries built from the stores."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from typing import Any

from deye_inverter.application.inverter_state import InverterState
from deye_inverter.domain.readings import Reading, reading_as_dict
from deye_inverter.domain.time_of_use import table_to_dicts
from deye_inverter.ports import (
    Clock,
    DailyEnergyRepository,
    ForecastRepository,
    ReadingRepository,
)

SERIES_FIELDS = (
    "solar_power",
    "load_power",
    "backup_load_power",
    "grid_power",
    "battery_power",
    "battery_soc",
)


class DashboardViews:
    def __init__(
        self,
        readings: ReadingRepository,
        forecasts: ForecastRepository,
        daily: DailyEnergyRepository,
        state: InverterState,
        clock: Clock,
    ) -> None:
        self._daily = daily
        self._readings = readings
        self._forecasts = forecasts
        self._state = state
        self._clock = clock

    def now(self) -> dict[str, Any]:
        latest = self._readings.latest()
        battery = self._state.battery_settings()
        return {
            "reading": reading_as_dict(latest) if latest else None,
            "age_seconds": self._age(latest),
            "battery_settings": asdict(battery) if battery else None,
            "charge_settings": self._charge_settings(),
        }

    def day_series(self, day: date) -> dict[str, Any]:
        start = self._midnight(day)
        readings = self._readings.between(start, start + timedelta(days=1))
        return {
            "day": day.isoformat(),
            "times": [r.taken_at.astimezone(start.tzinfo).strftime("%H:%M") for r in readings],
            **{name: [getattr(r, name) for r in readings] for name in SERIES_FIELDS},
        }

    def forecast(self, days: int = 3) -> dict[str, Any]:
        today = self._clock.now().date()
        start = self._midnight(today - timedelta(days=1))
        forecast = self._forecasts.load(start, start + timedelta(days=days + 1))
        zone = start.tzinfo
        return {
            "hours": [
                {
                    "hour_end": h.hour_end.astimezone(zone).isoformat(),
                    "solar_kwh": round(h.solar_kwh, 3),
                    "irradiance": h.irradiance,
                }
                for h in forecast.hours
            ],
            "days": [
                {
                    "day": d.isoformat(),
                    "forecast_kwh": round(forecast.energy_on(d), 2),
                    "actual_kwh": self._actual_total(d),
                }
                for d in (today - timedelta(days=1) + timedelta(days=i) for i in range(days + 1))
            ],
            "actual_hours": self._actual_hours(today - timedelta(days=1), today),
        }

    def time_of_use(self) -> dict[str, Any]:
        current = self._state.current_table()
        base = self._state.base_table()
        return {
            "current": table_to_dicts(current) if current else None,
            "current_read_at": self._state.current_table_read_at(),
            "base": table_to_dicts(base) if base else None,
            "charge_settings": self._charge_settings(),
        }

    def _charge_settings(self) -> dict[str, Any] | None:
        charge = self._state.charge_settings()
        if charge is None:
            return None
        return {**asdict(charge), "read_at": self._state.charge_settings_read_at()}

    def _actual_total(self, day: date) -> float | None:
        records = self._daily.between(day, day)
        return round(records[0].balance.solar, 2) if records else None

    def _actual_hours(self, first: date, last: date) -> list[dict[str, Any]]:
        readings = self._readings.between(
            self._midnight(first), self._midnight(last) + timedelta(days=1)
        )
        return hourly_energy(readings, self._midnight(first).tzinfo)

    def _midnight(self, day: date) -> datetime:
        return datetime.combine(day, time(0, 0), tzinfo=self._clock.now().tzinfo)

    def _age(self, latest: Reading | None) -> float | None:
        if latest is None:
            return None
        return round((self._clock.now() - latest.taken_at).total_seconds())


def hourly_energy(readings: list[Reading], zone: Any) -> list[dict[str, Any]]:
    """Solar energy per hour (hour = its end): mean solar power of the hour's samples."""
    per_hour: dict[datetime, list[float]] = {}
    for reading in readings:
        local = reading.taken_at.astimezone(zone)
        hour_end = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        per_hour.setdefault(hour_end, []).append(reading.solar_power)
    return [
        {"hour_end": hour_end.isoformat(), "solar_kwh": round(sum(v) / len(v) / 1000, 3)}
        for hour_end, v in sorted(per_hour.items())
    ]
