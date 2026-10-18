"""System clock in the site's time zone."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from deye_inverter.ports import Clock


class SystemClock(Clock):
    """:class:`Clock` that reads the machine's time, expressed in the site's time zone."""

    def __init__(self, timezone: str) -> None:
        self._zone = ZoneInfo(timezone)

    def now(self) -> datetime:
        """Returns the current time as an aware datetime in the site's time zone."""
        return datetime.now(self._zone)
