"""Expected house consumption by hour of the day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

HOURS_PER_DAY = 24
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class LoadProfile:
    """Average house load (kW) for each local clock hour, 0 to 23."""

    hourly_kw: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.hourly_kw) != HOURS_PER_DAY:
            raise ValueError(f"A load profile has {HOURS_PER_DAY} hourly values")

    @classmethod
    def flat(cls, kw: float) -> LoadProfile:
        return cls((kw,) * HOURS_PER_DAY)

    def energy_between(self, start: datetime, end: datetime) -> float:
        """Expected consumption in kWh between two moments (same time zone)."""
        total = 0.0
        moment = start
        while moment < end:
            next_hour = moment.replace(minute=0, second=0, microsecond=0) + HOUR
            segment_end = min(end, next_hour)
            total += self.hourly_kw[moment.hour] * ((segment_end - moment) / HOUR)
            moment = segment_end
        return total
