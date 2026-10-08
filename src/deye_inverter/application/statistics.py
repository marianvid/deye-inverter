"""Energy statistics per day, week, month, year and lifetime."""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from deye_inverter.domain.energy import DailyEnergy, EnergyBalance, total
from deye_inverter.domain.readings import Reading
from deye_inverter.ports import Clock, DailyEnergyRepository, ReadingRepository

CURVE_FIELDS = ("solar_power", "load_power", "grid_power", "battery_power", "battery_soc")
WEEK_CURVE_MINUTES = 15
LIFETIME_COUNTERS = {
    "solar": "PVCumulativePowerGenerationActive",
    "consumption": "CumulativeConsumption",
    "bought": "CumulativeEnergyPurchased",
    "charged": "TotalChargeEnergy",
    "discharged": "TotalDischargeEnergy",
}


class Period(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    LIFETIME = "lifetime"


@dataclass(frozen=True)
class Span:
    start: date
    end: date
    label: str
    previous: date | None
    next: date | None


class SpanCalculator:
    """Calendar arithmetic for each period (weeks start on Monday)."""

    def __init__(self, today: date, first_day: date) -> None:
        self._today = today
        self._first = first_day

    def span(self, period: Period, anchor: date) -> Span:
        builder: dict[Period, Callable[[date], Span]] = {
            Period.DAY: self._day,
            Period.WEEK: self._week,
            Period.MONTH: self._month,
            Period.YEAR: self._year,
            Period.LIFETIME: self._lifetime,
        }
        return builder[period](anchor)

    def _day(self, anchor: date) -> Span:
        one = timedelta(days=1)
        return self._make(anchor, anchor, f"{anchor:%A %d %B %Y}", anchor - one, anchor + one)

    def _week(self, anchor: date) -> Span:
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        label = f"Week {start:%d %b} to {end:%d %b %Y}"
        return self._make(start, end, label, start - timedelta(days=7), start + timedelta(days=7))

    def _month(self, anchor: date) -> Span:
        start = anchor.replace(day=1)
        end = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
        return self._make(
            start, end, f"{start:%B %Y}", start - timedelta(days=1), end + timedelta(days=1)
        )

    def _year(self, anchor: date) -> Span:
        start, end = date(anchor.year, 1, 1), date(anchor.year, 12, 31)
        return self._make(
            start, end, str(anchor.year), date(anchor.year - 1, 12, 31), date(anchor.year + 1, 1, 1)
        )

    def _lifetime(self, _: date) -> Span:
        return Span(self._first, self._today, f"Since {self._first:%d %B %Y}", None, None)

    def _make(self, start: date, end: date, label: str, previous: date, nxt: date) -> Span:
        return Span(
            start,
            end,
            label,
            previous if previous >= self._first else None,
            nxt if nxt <= self._today else None,
        )


class StatisticsViews:
    def __init__(
        self, daily: DailyEnergyRepository, readings: ReadingRepository, clock: Clock
    ) -> None:
        self._daily = daily
        self._readings = readings
        self._clock = clock

    def summary(self, period: Period, anchor: date | None = None) -> dict[str, Any]:
        today = self._clock.now().date()
        first = self._daily.first_day() or today
        span = SpanCalculator(today, first).span(period, min(anchor or today, today))
        records = self._daily.between(span.start, span.end)
        result: dict[str, Any] = {
            "period": period.value,
            "start": span.start.isoformat(),
            "end": span.end.isoformat(),
            "label": span.label,
            "previous": span.previous.isoformat() if span.previous else None,
            "next": span.next.isoformat() if span.next else None,
            "days_with_data": len(records),
            "totals": total(r.balance for r in records).as_dict(),
            "buckets": self._buckets(period, records),
        }
        result.update(self._extras(period, span))
        return result

    def _buckets(self, period: Period, records: list[DailyEnergy]) -> list[dict[str, Any]]:
        if period is Period.DAY:
            return []
        keyers: dict[Period, Callable[[date], str]] = {
            Period.WEEK: lambda d: d.isoformat(),
            Period.MONTH: lambda d: d.isoformat(),
            Period.YEAR: lambda d: f"{d:%Y-%m}",
            Period.LIFETIME: lambda d: f"{d:%Y}",
        }
        return grouped(records, keyers[period])

    def _extras(self, period: Period, span: Span) -> dict[str, Any]:
        if period in (Period.DAY, Period.WEEK):
            minutes = 0 if period is Period.DAY else WEEK_CURVE_MINUTES
            return {"curve": self._curve(span, minutes)}
        if period is Period.MONTH:
            return {"soc_by_day": self._soc_by_day(span)}
        if period is Period.LIFETIME:
            return {"inverter_counters": self._inverter_counters()}
        return {}

    def _curve(self, span: Span, minutes: int) -> dict[str, Any]:
        readings = self._readings.between(
            self._midnight(span.start), self._midnight(span.end + timedelta(days=1))
        )
        zone = self._clock.now().tzinfo
        points = averaged(readings, minutes) if minutes else readings
        fmt = "%H:%M" if not minutes else "%a %H:%M"
        return {
            "times": [r.taken_at.astimezone(zone).strftime(fmt) for r in points],
            **{name: [round(getattr(r, name), 1) for r in points] for name in CURVE_FIELDS},
        }

    def _soc_by_day(self, span: Span) -> list[dict[str, Any]]:
        readings = self._readings.between(
            self._midnight(span.start), self._midnight(span.end + timedelta(days=1))
        )
        zone = self._clock.now().tzinfo
        per_day: dict[str, list[float]] = defaultdict(list)
        for r in readings:
            per_day[r.taken_at.astimezone(zone).date().isoformat()].append(r.battery_soc)
        return [{"day": day, "min": min(v), "max": max(v)} for day, v in sorted(per_day.items())]

    def _inverter_counters(self) -> dict[str, Any] | None:
        latest = self._readings.latest()
        if latest is None or not latest.raw:
            return None
        values = {name: _number(latest.raw.get(key)) for name, key in LIFETIME_COUNTERS.items()}
        return EnergyBalance(**values).as_dict()

    def _midnight(self, day: date) -> datetime:
        return datetime.combine(day, time(0, 0), tzinfo=self._clock.now().tzinfo)


def grouped(records: Iterable[DailyEnergy], key: Callable[[date], str]) -> list[dict[str, Any]]:
    groups: dict[str, list[EnergyBalance]] = defaultdict(list)
    for record in records:
        groups[key(record.day)].append(record.balance)
    return [{"label": label, **total(groups[label]).as_dict()} for label in sorted(groups)]


def averaged(readings: list[Reading], minutes: int) -> list[Reading]:
    """Averages readings into fixed buckets so long curves stay light."""
    buckets: dict[datetime, list[Reading]] = defaultdict(list)
    for reading in readings:
        stamp = reading.taken_at
        floored = stamp - timedelta(
            minutes=stamp.minute % minutes, seconds=stamp.second, microseconds=stamp.microsecond
        )
        buckets[floored].append(reading)
    return [_mean(stamp, group) for stamp, group in sorted(buckets.items())]


def _mean(stamp: datetime, group: list[Reading]) -> Reading:
    first = group[0]
    means = {name: sum(getattr(r, name) for r in group) / len(group) for name in CURVE_FIELDS}
    return Reading(
        taken_at=stamp,
        backup_load_power=first.backup_load_power,
        battery_voltage=first.battery_voltage,
        solar_today=first.solar_today,
        load_today=first.load_today,
        grid_bought_today=first.grid_bought_today,
        battery_charged_today=first.battery_charged_today,
        battery_discharged_today=first.battery_discharged_today,
        **means,
    )


def _number(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0
