"""System clock in the site's time zone."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from deye_inverter.ports import Clock


class SystemClock(Clock):
    def __init__(self, timezone: str) -> None:
        self._zone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self._zone)
