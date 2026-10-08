"""A charge ordered by hand: "charge to X %", now or ready by a time, held until a time.

While it is active it overrides every planner rule in the slots it needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from deye_inverter.domain.rules import (
    JustInTimeCharge,
    PlannerContext,
    PlannerRule,
    RuleOutcome,
)
from deye_inverter.domain.settings import TuningSettings
from deye_inverter.domain.time_of_use import TimeOfUseSlot

NAME = "manual"
DEFAULT_MAX_HOURS = 48


class ManualChargeError(ValueError):
    pass


@dataclass(frozen=True)
class ManualCharge:
    """``ready_at`` None means "start now". ``hold_until`` None means "release as
    soon as the target is reached" (now) or "release at the ready time"."""

    target_soc: int
    created_at: datetime
    ready_at: datetime | None = None
    hold_until: datetime | None = None
    # The grid charge master switch was off and was turned on for this charge.
    restore_grid_switch_off: bool = False
    # The charge ends after this many hours whatever was asked (Settings, Tuning).
    max_hours: int = DEFAULT_MAX_HOURS

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(hours=self.max_hours)

    def __post_init__(self) -> None:
        if not 1 <= self.target_soc <= 100:
            raise ManualChargeError("The target must be between 1 and 100 %")
        if self.ready_at is not None and self.ready_at <= self.created_at:
            raise ManualChargeError("The ready time must be in the future")
        start = self.ready_at or self.created_at
        if self.hold_until is not None and self.hold_until < start:
            raise ManualChargeError("Hold until must not be earlier than the start")
        if (self.hold_until or start) > self.expires_at:
            raise ManualChargeError(f"A manual charge can last at most {self.max_hours} hours")

    @property
    def release_at(self) -> datetime | None:
        """When the charge ends by time; ``None`` for "now" until the target is reached."""
        if self.hold_until is not None:
            return self.hold_until
        return self.ready_at

    def finished(self, now: datetime, soc: float) -> bool:
        if now >= self.expires_at:
            return True
        if self.ready_at is None:
            reached = soc >= self.target_soc
            return reached and (self.hold_until is None or now >= self.hold_until)
        release = self.release_at
        return release is not None and now >= release

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_soc": self.target_soc,
            "created_at": self.created_at.isoformat(),
            "ready_at": self.ready_at.isoformat() if self.ready_at else None,
            "hold_until": self.hold_until.isoformat() if self.hold_until else None,
            "restore_grid_switch_off": self.restore_grid_switch_off,
            "max_hours": self.max_hours,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManualCharge:
        def moment(key: str) -> datetime | None:
            value = data.get(key)
            return datetime.fromisoformat(value) if value else None

        created = moment("created_at")
        if created is None:
            raise ManualChargeError("A stored manual charge has no creation time")
        return cls(
            target_soc=int(data["target_soc"]),
            created_at=created,
            ready_at=moment("ready_at"),
            hold_until=moment("hold_until"),
            restore_grid_switch_off=bool(data.get("restore_grid_switch_off", False)),
            max_hours=int(data.get("max_hours", DEFAULT_MAX_HOURS)),
        )


class ManualChargeRule(PlannerRule):
    """Applied after every other rule, so its slots win."""

    name = NAME

    def __init__(self, charge: ManualCharge | None, tuning: TuningSettings) -> None:
        self._charge = charge
        self._planner = JustInTimeCharge(NAME, tuning)

    def evaluate(self, context: PlannerContext) -> RuleOutcome:
        charge = self._charge
        if charge is None:
            return RuleOutcome(self.name, "No manual charge.")
        target = charge.target_soc
        if charge.ready_at is not None and context.now < charge.ready_at:
            outcome = self._planner.plan(context, charge.ready_at, target)
            overrides = dict(outcome.overrides)
            overrides.update(
                {
                    i: slot
                    for i, slot in self._hold(context, charge.ready_at, charge).items()
                    if i not in overrides
                }
            )
            summary = f"Manual: {target}% by {charge.ready_at:%a %H:%M}. {outcome.summary}"
            return RuleOutcome(self.name, summary, overrides, outcome.figures)
        overrides = self._hold(context, context.now, charge)
        until = charge.hold_until
        held = f" and held until {until:%a %H:%M}" if until and until > context.now else ""
        summary = f"Manual: charging to {target}% now{held}."
        return RuleOutcome(self.name, summary, overrides, {"target_soc": target})

    @staticmethod
    def _hold(
        context: PlannerContext, start: datetime, charge: ManualCharge
    ) -> dict[int, TimeOfUseSlot]:
        """Slots from ``start`` to the hold end get the target with grid charge on."""
        end = max(charge.hold_until or start, start) + timedelta(minutes=1)
        table = context.base_table
        start_minute = start.hour * 60 + start.minute
        end_minute = end.hour * 60 + end.minute
        if end - start >= timedelta(days=1):
            indexes = list(range(len(table.slots)))
        else:
            indexes = table.indexes_overlapping(start_minute, end_minute)
        return {
            i: table.slots[i].with_changes(soc=charge.target_soc, grid_charge=True) for i in indexes
        }
