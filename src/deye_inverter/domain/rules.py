"""Planner rules (Strategy pattern).

Each rule looks at a :class:`PlannerContext` and returns slot overrides for the
Time of Use table plus the figures that explain its choice. Rules never do I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.load import LoadProfile
from deye_inverter.domain.settings import FloorSettings, SiteSettings, TuningSettings
from deye_inverter.domain.time_of_use import TimeOfUseError, TimeOfUseSlot, TimeOfUseTable

# Guards a division when the inverter reports no charging power at all.
MIN_CHARGE_KW = 0.1


@dataclass(frozen=True)
class PlannerContext:
    now: datetime
    soc: float
    base_table: TimeOfUseTable
    forecast: Forecast
    solar_ratio: float
    load: LoadProfile
    grid_charge_kw: float
    site: SiteSettings
    # Lowest SOC the battery runs down to outside reserve slots (the floor rule).
    floor_soc: int = 20
    # The table the inverter has now; keeps a planned start stable between checks.
    current_table: TimeOfUseTable | None = None


@dataclass(frozen=True)
class RuleOutcome:
    rule: str
    summary: str
    overrides: dict[int, TimeOfUseSlot] = field(default_factory=dict)
    figures: dict[str, float | str] = field(default_factory=dict)


class PlannerRule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, context: PlannerContext) -> RuleOutcome: ...


def clamp_soc(value: int, site: SiteSettings) -> int:
    return max(site.min_soc, min(100, value))


def _at(day: date, moment: time, like: datetime) -> datetime:
    return datetime.combine(day, moment, tzinfo=like.tzinfo)


def round_down(moment: datetime, step_minutes: int) -> datetime:
    extra = moment.minute % max(1, step_minutes)
    return moment.replace(second=0, microsecond=0) - timedelta(minutes=extra)


class JustInTimeCharge:
    """Gets the battery to a target SOC by a deadline: the grid only when the sun and
    the battery cannot get there, and as late as possible (the start of the slot
    holding the deadline is moved). Shared by the reserve and manual charges."""

    def __init__(self, name: str, tuning: TuningSettings) -> None:
        self._name = name
        self._tuning = tuning
        self._tolerance = timedelta(minutes=tuning.start_tolerance_minutes)

    def plan(self, context: PlannerContext, deadline: datetime, target_soc: int) -> RuleOutcome:
        return self._decide(context, deadline, target_soc, self._project(context, deadline))

    @staticmethod
    def _project(context: PlannerContext, deadline: datetime) -> dict[str, float]:
        hours = (deadline - context.now) / timedelta(hours=1)
        solar = context.forecast.energy_between(context.now, deadline) * context.solar_ratio
        load = context.load.energy_between(context.now, deadline)
        projected = context.soc + (solar - load) / context.site.battery_kwh * 100
        # The battery stops discharging at the floor; below it the house uses the grid.
        projected = max(projected, min(context.soc, context.floor_soc))
        return {
            "hours_left": round(hours, 2),
            "solar_kwh": round(solar, 2),
            "load_kwh": round(load, 2),
            "projected_soc": round(max(0.0, min(100.0, projected)), 1),
        }

    def _decide(
        self,
        context: PlannerContext,
        deadline: datetime,
        target_soc: int,
        projection: dict[str, float],
    ) -> RuleOutcome:
        target = clamp_soc(target_soc, context.site)
        figures: dict[str, float | str] = {**projection, "target_soc": target}
        deficit_kwh = (target - projection["projected_soc"]) / 100 * context.site.battery_kwh
        if deficit_kwh <= 0:
            overrides = self._slots(context, deadline, deadline, target, grid_charge=False)
            summary = f"{target}% at {deadline:%H:%M} is reached without the grid."
            return RuleOutcome(self._name, summary, overrides, figures)
        hours_needed = deficit_kwh / max(context.grid_charge_kw, MIN_CHARGE_KW)
        margin = self._tuning.charge_margin
        planned = self._round(deadline - timedelta(hours=hours_needed * margin))
        start = self._stable_start(context, deadline, planned)
        figures.update(deficit_kwh=round(deficit_kwh, 2), grid_hours=round(hours_needed, 2))
        figures["grid_from"] = start.strftime("%H:%M")
        moved = self._moved_slot(context, start, deadline, target)
        overrides = (
            moved
            if moved is not None
            else self._slots(context, start, deadline, target, grid_charge=True)
        )
        when = "now" if start <= context.now else f"at {start:%H:%M}"
        summary = f"Short by {deficit_kwh:.1f} kWh: grid charge starts {when}."
        return RuleOutcome(self._name, summary, overrides, figures)

    def _stable_start(
        self, context: PlannerContext, deadline: datetime, planned: datetime
    ) -> datetime:
        """Start of grid charging: as late as the estimate allows, but steady.

        A start already on the inverter is kept while charging is under way, or
        while the new estimate is within the tolerance (fewer writes). A late
        estimate means "now".
        """
        tolerance = self._tolerance
        current = self._current_start(context, deadline)
        if current is not None and current <= context.now:
            untouched = current.time() == slot_holding(context.base_table, deadline).start
            if not (untouched and planned > context.now + tolerance):
                return current
        elif current is not None and abs(planned - current) <= tolerance:
            return current
        return max(planned, self._round(context.now))

    def _round(self, moment: datetime) -> datetime:
        """Starts are rounded down (earlier is the safe side)."""
        return round_down(moment, self._tuning.start_step_minutes)

    @staticmethod
    def _current_start(context: PlannerContext, deadline: datetime) -> datetime | None:
        """Start the inverter has for the slot this deadline moves, if it grid-charges.

        The slot is found by its position in the base table, not by the time: once a
        later deadline has moved its own slot earlier (17:00's slot starting at 15:30),
        that slot covers this deadline (16:00) too, and its start is not this one.
        """
        table = context.current_table
        if table is None:
            return None
        slot = table.slots[context.base_table.index_at(deadline.time())]
        return last_before(slot.start, deadline) if slot.grid_charge else None

    def _moved_slot(
        self, context: PlannerContext, start: datetime, deadline: datetime, soc: int
    ) -> dict[int, TimeOfUseSlot] | None:
        """Moves the start of the slot holding the deadline to ``start``.

        Grid charging then begins only at ``start``; until then the previous slot
        applies. ``None`` when ``start`` falls too early for the previous slot.
        """
        table = context.base_table
        index = table.index_at(deadline.time())
        previous = table.slots[index - 1]
        slot_start = last_before(table.slots[index].start, deadline)
        step = timedelta(minutes=self._tuning.start_step_minutes)
        earliest = last_before(previous.start, slot_start) + step
        if start < earliest:
            return None
        moved = table.slots[index].with_changes(
            start=min(start, deadline).time(), soc=soc, grid_charge=True
        )
        try:
            table.replace_slots({index: moved})
        except TimeOfUseError:
            return None
        return {index: moved}

    @staticmethod
    def _slots(
        context: PlannerContext, start: datetime, deadline: datetime, soc: int, grid_charge: bool
    ) -> dict[int, TimeOfUseSlot]:
        table = context.base_table
        start_minute = start.hour * 60 + start.minute
        deadline_minute = deadline.hour * 60 + deadline.minute
        indexes = table.indexes_overlapping(start_minute, deadline_minute + 1)
        return {i: table.slots[i].with_changes(soc=soc, grid_charge=grid_charge) for i in indexes}


class FloorRule(PlannerRule):
    """Every slot lets the battery run down to the floor; later rules raise the slots
    they protect."""

    name = "floor"

    def __init__(self, settings: FloorSettings) -> None:
        self._settings = settings

    def evaluate(self, context: PlannerContext) -> RuleOutcome:
        soc = clamp_soc(self._settings.soc, context.site)
        grid = self._settings.grid_charge
        overrides = {
            i: slot.with_changes(soc=soc, grid_charge=grid)
            for i, slot in enumerate(context.base_table)
        }
        summary = f"Battery may run down to {soc}% wherever no reserve applies."
        return RuleOutcome(self.name, summary, overrides, {"floor_soc": soc})


def slot_holding(table: TimeOfUseTable, moment: datetime) -> TimeOfUseSlot:
    return table.slots[table.index_at(moment.time())]


def last_before(moment: time, limit: datetime) -> datetime:
    """The latest occurrence of clock time ``moment`` not after ``limit``."""
    candidate = _at(limit.date(), moment, limit)
    return candidate if candidate <= limit else candidate - timedelta(days=1)


def next_after(moment: time, now: datetime) -> datetime:
    """The next occurrence of clock time ``moment`` after ``now``."""
    candidate = _at(now.date(), moment, now)
    return candidate if candidate > now else candidate + timedelta(days=1)


def running_since(table: TimeOfUseTable, moment: time, now: datetime) -> datetime | None:
    """The last occurrence of ``moment`` if the slot holding it is running now."""
    index = table.index_at(moment)
    slot_start = last_before(table.slots[index].start, now)
    length = table.end_minute(index) - table.slots[index].start_minute
    last = last_before(moment, now)
    running = slot_start <= last and now < slot_start + timedelta(minutes=length)
    return last if running else None
