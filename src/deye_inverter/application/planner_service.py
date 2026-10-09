"""Runs the planner rules and, depending on the mode, sends the result."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from deye_inverter.application.energy_model import EnergyModel, today_solar
from deye_inverter.application.inverter_state import InverterState
from deye_inverter.application.time_of_use_service import TimeOfUseService
from deye_inverter.domain.manual import ManualCharge, ManualChargeRule
from deye_inverter.domain.reserve import ReserveRule
from deye_inverter.domain.rules import FloorRule, PlannerContext, PlannerRule, RuleOutcome
from deye_inverter.domain.settings import Mode, PlannerSettings
from deye_inverter.domain.time_of_use import (
    TimeOfUseError,
    TimeOfUseSlot,
    TimeOfUseTable,
    table_to_dicts,
)
from deye_inverter.ports import (
    Clock,
    ForecastRepository,
    JournalRepository,
    ReadingRepository,
    SettingsRepository,
)

LOG = logging.getLogger(__name__)
DECISION = "decision"
FORECAST_HORIZON = timedelta(days=2)


@dataclass
class Decision:
    at: datetime
    mode: Mode
    trigger: str
    status: str
    message: str
    outcomes: list[RuleOutcome] = field(default_factory=list)
    desired: TimeOfUseTable | None = None
    changed_slots: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "trigger": self.trigger,
            "status": self.status,
            "message": self.message,
            "rules": [
                {"rule": o.rule, "summary": o.summary, "figures": o.figures} for o in self.outcomes
            ],
            "desired": table_to_dicts(self.desired) if self.desired else None,
            "changed_slots": self.changed_slots,
        }


def merge_slot(table: TimeOfUseTable, index: int, slot: TimeOfUseSlot) -> TimeOfUseTable:
    try:
        return table.replace_slots({index: slot})
    except TimeOfUseError:
        return table.replace_slots({index: slot.with_changes(start=table.slots[index].start)})


@dataclass(frozen=True)
class PlannerDependencies:
    """Parameter object: what the planner reads and what it acts through."""

    settings: SettingsRepository
    state: InverterState
    readings: ReadingRepository
    forecasts: ForecastRepository
    energy: EnergyModel
    commands: TimeOfUseService
    journal: JournalRepository
    clock: Clock
    refresh_forecast: Callable[[], None] | None = None
    manual_charge: Callable[[], ManualCharge | None] | None = None


class PlannerService:
    def __init__(self, deps: PlannerDependencies) -> None:
        self._manual_charge = deps.manual_charge or (lambda: None)
        self._refresh_forecast = deps.refresh_forecast
        self._settings = deps.settings
        self._state = deps.state
        self._readings = deps.readings
        self._forecasts = deps.forecasts
        self._energy = deps.energy
        self._commands = deps.commands
        self._journal = deps.journal
        self._clock = deps.clock

    def run(self, trigger: str) -> Decision:
        settings = self._settings.load()
        note = self._fresh_forecast() if settings.mode is not Mode.OFF else ""
        decision = self._decide(settings, trigger)
        if note:
            decision.message = f"{decision.message} {note}"
        self._journal.add(DECISION, decision.at, decision.as_dict())
        return decision

    def _fresh_forecast(self) -> str:
        """Fetches the forecast again so every check judges the latest weather."""
        if self._refresh_forecast is None:
            return ""
        try:
            self._refresh_forecast()
        except Exception as error:
            LOG.warning("Forecast refresh before the planner failed: %s", error)
            return "(Forecast refresh failed; used the stored forecast.)"
        return ""

    def preview(self) -> Decision:
        """Evaluate the rules now without sending or recording anything."""
        settings = self._settings.load()
        return self._evaluate(settings, "preview", self._clock.now())

    def _decide(self, settings: PlannerSettings, trigger: str) -> Decision:
        now = self._clock.now()
        if settings.mode is Mode.OFF:
            return Decision(now, settings.mode, trigger, "off", "Automation is off.")
        decision = self._evaluate(settings, trigger, now)
        if decision.status == "change":
            self._apply(settings, decision)
        return decision

    def _evaluate(self, settings: PlannerSettings, trigger: str, now: datetime) -> Decision:
        context = self._context(settings, now)
        if context is None:
            return Decision(now, settings.mode, trigger, "skipped", "No data yet (table or SOC).")
        outcomes = [rule.evaluate(context) for rule in self._rules(settings, self._manual_charge())]
        desired = self._merge(context.base_table, outcomes)
        current = self._state.current_table() or context.base_table
        changed = desired.differences(current)
        status = "change" if changed else "no-change"
        message = "Inverter table already matches." if not changed else "Table differs."
        return Decision(now, settings.mode, trigger, status, message, outcomes, desired, changed)

    def _apply(self, settings: PlannerSettings, decision: Decision) -> None:
        if decision.desired is None:
            return
        if settings.mode is Mode.DRY_RUN:
            decision.status, decision.message = "dry-run", "Would send the table (dry-run)."
            return
        manual = self._manual_charge() is not None or decision.trigger.startswith("manual charge")
        urgent = self._protects_more(decision.desired)
        if not manual:
            held = self._held_back(settings, decision.at, urgent)
            if held is not None:
                decision.status, decision.message = held
                return
        outcome = self._commands.send(decision.desired, f"planner ({decision.trigger})")
        decision.status, decision.message = outcome.status, outcome.message
        if urgent and not manual:
            decision.message += " (protection raised: sent regardless of the write limits)"

    def _protects_more(self, desired: TimeOfUseTable) -> bool:
        current = self._state.current_table()
        return current is None or desired.protects_more_than(current)

    def _held_back(
        self, settings: PlannerSettings, now: datetime, urgent: bool
    ) -> tuple[str, str] | None:
        """Write limits, a safety net against a planner fault. A table that keeps more in
        the battery is sent anyway, up to its own daily limit; one that lowers the
        protection or moves a grid start later waits."""
        writes = self._commands.writes_today()
        if urgent:
            if writes >= settings.max_raising_writes_per_day:
                return "limit", "Daily write limit reached, even for raising the protection."
            return None
        if writes >= settings.max_writes_per_day:
            return "limit", "Daily write limit reached."
        last = self._commands.last_write_at()
        gap = timedelta(minutes=settings.min_minutes_between_writes)
        if last is not None and now - last < gap:
            return "wait", f"Next write allowed at {(last + gap).astimezone(now.tzinfo):%H:%M}."
        return None

    def _context(self, settings: PlannerSettings, now: datetime) -> PlannerContext | None:
        base = self._state.base_table()
        latest = self._readings.latest()
        if base is None or latest is None:
            return None
        forecast = self._forecasts.load(now - timedelta(days=1), now + FORECAST_HORIZON)
        return PlannerContext(
            now=now,
            soc=latest.battery_soc,
            base_table=base,
            forecast=forecast,
            solar_ratio=self._energy.solar_ratio(
                now, forecast, today_solar(latest, now), settings.tuning
            ),
            load=self._energy.load_profile(now, settings.site),
            grid_charge_kw=self._energy.grid_charge_kw(
                self._state.battery_settings(),
                self._state.charge_settings(),
                settings.site,
                settings.tuning,
            ),
            site=settings.site,
            floor_soc=max(settings.site.min_soc, settings.floor.soc),
            current_table=self._state.current_table(),
        )

    @staticmethod
    def _rules(settings: PlannerSettings, manual: ManualCharge | None) -> list[PlannerRule]:
        """Applied in order, later rules win where they touch the same slot:
        floor everywhere, then the outage reserve, then a manual charge."""
        return [
            FloorRule(settings.floor),
            ReserveRule(settings.reserve, settings.tuning),
            ManualChargeRule(manual, settings.tuning),
        ]

    @staticmethod
    def _merge(base: TimeOfUseTable, outcomes: list[RuleOutcome]) -> TimeOfUseTable:
        """Applies the rules in order. A moved start that would cross a neighbouring
        slot (two rules moving adjacent slots) keeps the start the table had."""
        table = base
        for outcome in outcomes:
            for index, slot in outcome.overrides.items():
                table = merge_slot(table, index, slot)
        return table
