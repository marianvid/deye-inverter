"""Reserve rule: the protected slots hold what a grid outage would need.

Protected moments: ``protect_from`` and every slot start after it, before
``protect_until``. For each moment:

- its slot is running now: the slot holds the reserve computed for the moment
  (the need only shrinks as the night passes); grid charge at once if the battery
  is already below it;
- the moment is still ahead: the battery must reach the reserve by then, from the
  grid only if needed and as late as possible (:class:`JustInTimeCharge`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time

from deye_inverter.domain.outage import OutageLoad, OutageSimulation
from deye_inverter.domain.rules import (
    JustInTimeCharge,
    PlannerContext,
    PlannerRule,
    RuleOutcome,
    next_after,
    running_since,
)
from deye_inverter.domain.settings import ReserveSettings, TuningSettings
from deye_inverter.domain.time_of_use import TimeOfUseError, TimeOfUseSlot, TimeOfUseTable

NAME = "reserve"
DAY_MINUTES = 24 * 60


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


class ReserveRule(PlannerRule):
    name = NAME

    def __init__(self, settings: ReserveSettings, tuning: TuningSettings) -> None:
        self._settings = settings
        self._tuning = tuning
        self._charge = JustInTimeCharge(NAME, tuning)

    def moments(self, table: TimeOfUseTable) -> list[time]:
        """``protect_from`` and every slot start after it, before ``protect_until``."""
        start = _minutes(self._settings.protect_from)
        span = (_minutes(self._settings.protect_until) - start) % DAY_MINUTES

        def offset(moment: time) -> int:
            return (_minutes(moment) - start) % DAY_MINUTES

        later = sorted((s.start for s in table if 0 < offset(s.start) < span), key=offset)
        return [self._settings.protect_from, *later]

    def evaluate(self, context: PlannerContext) -> RuleOutcome:
        if not self._settings.enabled:
            return RuleOutcome(self.name, "Disabled; the floor applies everywhere.")
        simulation = OutageSimulation(
            self._settings,
            OutageLoad(self._settings, context.load),
            context.forecast,
            context.site.battery_kwh,
            context.site.min_soc,
        )
        plan = _Plan(context, self._tuning.soc_tolerance)
        for moment in self.moments(context.base_table):
            since = running_since(context.base_table, moment, context.now)
            when = since or next_after(moment, context.now)
            if not self._settings.applies_on(when.date()):
                continue
            required = simulation.required_at(when)
            if since is not None:
                self._hold(context, moment, required, plan)
            else:
                self._prepare(context, moment, when, required, plan)
        return plan.outcome(self.name)

    @staticmethod
    def _hold(context: PlannerContext, moment: time, required: int, plan: _Plan) -> None:
        index = context.base_table.index_at(moment)
        short = context.soc < required
        slot = context.base_table.slots[index].with_changes(soc=required, grid_charge=short)
        plan.add(moment, required, {index: slot})
        if short:
            plan.notes.append(f"below the {moment:%H:%M} reserve now: grid charge on")

    def _prepare(
        self,
        context: PlannerContext,
        moment: time,
        when: datetime,
        required: int,
        plan: _Plan,
    ) -> None:
        # Each moment plans against the table as the earlier moments left it.
        outcome = self._charge.plan(replace(context, base_table=plan.table()), when, required)
        plan.add(moment, required, outcome.overrides)
        if "grid_from" in outcome.figures:
            grid_from = outcome.figures["grid_from"]
            plan.figures[f"grid from (for {moment:%H:%M})"] = grid_from
            plan.notes.append(f"grid charge for {moment:%H:%M} from {grid_from}")


class _Plan:
    """Slots, figures and notes collected over the protected moments."""

    def __init__(self, context: PlannerContext, soc_tolerance: int) -> None:
        self._context = context
        self._tolerance = soc_tolerance
        self.overrides: dict[int, TimeOfUseSlot] = {}
        self.figures: dict[str, float | str] = {}
        self.notes: list[str] = []
        self._levels: list[str] = []

    def table(self) -> TimeOfUseTable:
        return self._context.base_table.replace_slots(self.overrides)

    def add(self, moment: time, required: int, slots: dict[int, TimeOfUseSlot]) -> None:
        for index, slot in slots.items():
            if index in self.overrides:
                continue
            slot = self._steady(index, slot)
            try:
                self.table().replace_slots({index: slot})
            except TimeOfUseError:  # a moved start would cross a slot moved earlier
                slot = slot.with_changes(start=self.table().slots[index].start)
            self.overrides[index] = slot
        self.figures[f"reserve {moment:%H:%M}"] = required
        self._levels.append(f"{moment:%H:%M} {required}%")

    def _steady(self, index: int, slot: TimeOfUseSlot) -> TimeOfUseSlot:
        """Keeps the inverter's SOC when the new one is within the tolerance (fewer writes)."""
        current = self._context.current_table
        if current is None:
            return slot
        on_inverter = current.slots[index]
        same = on_inverter.start == slot.start and on_inverter.grid_charge == slot.grid_charge
        if same and abs(on_inverter.soc - slot.soc) <= self._tolerance:
            return slot.with_changes(soc=on_inverter.soc)
        return slot

    def outcome(self, name: str) -> RuleOutcome:
        if not self._levels:
            return RuleOutcome(name, "Not active today; the floor applies everywhere.")
        tail = f" Short: {'; '.join(self.notes)}." if self.notes else " Reached without the grid."
        summary = f"Outage reserve: {', '.join(self._levels)}.{tail}"
        return RuleOutcome(name, summary, self.overrides, self.figures)
