"""The inverter's Time of Use table: six slots, each active from its start time
until the next slot's start time (the last slot wraps past midnight)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import time
from typing import Any

SLOT_COUNT = 6
MIN_SOC = 0
MAX_SOC = 100
MINUTES_PER_DAY = 24 * 60


class TimeOfUseError(ValueError):
    """Raised for an invalid Time of Use table."""


@dataclass(frozen=True)
class TimeOfUseSlot:
    start: time
    soc: int
    power: int
    voltage: float
    grid_charge: bool
    generator_charge: bool

    def __post_init__(self) -> None:
        if not MIN_SOC <= self.soc <= MAX_SOC:
            raise TimeOfUseError(f"SOC {self.soc} outside {MIN_SOC}..{MAX_SOC}")
        if self.power < 0:
            raise TimeOfUseError("Power cannot be negative")

    @property
    def start_minute(self) -> int:
        return self.start.hour * 60 + self.start.minute

    def with_changes(self, **changes: Any) -> TimeOfUseSlot:
        return replace(self, **changes)


@dataclass(frozen=True)
class TimeOfUseTable:
    slots: tuple[TimeOfUseSlot, ...]

    def __post_init__(self) -> None:
        if len(self.slots) != SLOT_COUNT:
            raise TimeOfUseError(f"A table has exactly {SLOT_COUNT} slots")
        starts = [slot.start_minute for slot in self.slots]
        if starts != sorted(starts) or len(set(starts)) != SLOT_COUNT:
            raise TimeOfUseError("Slot start times must be distinct and ascending")

    def __iter__(self) -> Iterator[TimeOfUseSlot]:
        return iter(self.slots)

    def end_minute(self, index: int) -> int:
        """End of slot ``index`` in minutes from midnight (may exceed one day)."""
        if index + 1 < SLOT_COUNT:
            return self.slots[index + 1].start_minute
        return self.slots[0].start_minute + MINUTES_PER_DAY

    def index_at(self, moment: time) -> int:
        """Index of the slot active at ``moment``."""
        minute = moment.hour * 60 + moment.minute
        active = SLOT_COUNT - 1
        for index, slot in enumerate(self.slots):
            if slot.start_minute <= minute:
                active = index
        return active

    def indexes_overlapping(self, start_minute: int, end_minute: int) -> list[int]:
        """Indexes of slots overlapping the window [start, end) on one day.

        ``end_minute`` may be lower than ``start_minute`` for a window that
        crosses midnight.
        """
        windows = self._split_window(start_minute, end_minute)
        return [
            index
            for index in range(SLOT_COUNT)
            if any(self._overlaps(index, low, high) for low, high in windows)
        ]

    def replace_slots(self, changes: dict[int, TimeOfUseSlot]) -> TimeOfUseTable:
        return TimeOfUseTable(tuple(changes.get(i, slot) for i, slot in enumerate(self.slots)))

    def differences(self, other: TimeOfUseTable) -> list[int]:
        pairs = enumerate(zip(self.slots, other.slots, strict=True))
        return [i for i, (mine, theirs) in pairs if mine != theirs]

    def describe_changes(self, before: TimeOfUseTable) -> list[str]:
        """What changes from ``before`` to this table, one line per slot, in words.

        A slot is named by its start in ``before``: "01:00: SOC 50% → 90%, grid charge on".
        """
        lines = []
        for old, new in zip(before.slots, self.slots, strict=True):
            parts = []
            if new.start != old.start:
                parts.append(f"starts {new.start:%H:%M}")
            if new.soc != old.soc:
                parts.append(f"SOC {old.soc}% → {new.soc}%")
            if new.grid_charge != old.grid_charge:
                parts.append(f"grid charge {'on' if new.grid_charge else 'off'}")
            if new.power != old.power:
                parts.append(f"power {old.power} → {new.power} W")
            if new.voltage != old.voltage:
                parts.append(f"voltage {old.voltage:g} → {new.voltage:g} V")
            if new.generator_charge != old.generator_charge:
                parts.append(f"generator charge {'on' if new.generator_charge else 'off'}")
            if parts:
                lines.append(f"{old.start:%H:%M}: {', '.join(parts)}")
        return lines

    def protects_more_than(self, other: TimeOfUseTable) -> bool:
        """True when this table keeps more in the battery than ``other`` somewhere:
        a higher slot SOC, grid charge switched on, or grid charging starting earlier."""
        for mine, theirs in zip(self.slots, other.slots, strict=True):
            if mine.soc > theirs.soc:
                return True
            if mine.grid_charge and (not theirs.grid_charge or mine.start < theirs.start):
                return True
        return False

    @staticmethod
    def _split_window(start: int, end: int) -> list[tuple[int, int]]:
        if end > start:
            return [(start, end)]
        return [(start, MINUTES_PER_DAY), (0, end)]

    def _overlaps(self, index: int, low: int, high: int) -> bool:
        slot_start = self.slots[index].start_minute
        slot_end = self.end_minute(index)
        segments = [(slot_start, min(slot_end, MINUTES_PER_DAY))]
        if slot_end > MINUTES_PER_DAY:
            segments.append((0, slot_end - MINUTES_PER_DAY))
        return any(s < high and low < e for s, e in segments)


def table_from_slots(slots: Iterable[TimeOfUseSlot]) -> TimeOfUseTable:
    return TimeOfUseTable(tuple(slots))


def table_to_dicts(table: TimeOfUseTable) -> list[dict[str, Any]]:
    """Plain JSON form used by the web API and the key-value store."""
    return [
        {
            "start": slot.start.strftime("%H:%M"),
            "soc": slot.soc,
            "power": slot.power,
            "voltage": slot.voltage,
            "grid_charge": slot.grid_charge,
            "generator_charge": slot.generator_charge,
        }
        for slot in table
    ]


def table_from_dicts(items: Iterable[dict[str, Any]]) -> TimeOfUseTable:
    return table_from_slots(
        TimeOfUseSlot(
            start=time.fromisoformat(str(item["start"])),
            soc=int(item["soc"]),
            power=int(item["power"]),
            voltage=float(item.get("voltage", 0)),
            grid_charge=bool(item.get("grid_charge")),
            generator_charge=bool(item.get("generator_charge")),
        )
        for item in items
    )
