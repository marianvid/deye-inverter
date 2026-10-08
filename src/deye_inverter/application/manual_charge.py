"""Manual charge commands: start, follow and end a "charge to X %" order."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import Any

from deye_inverter.application.charge_service import SETTING, ChargeSettingsService
from deye_inverter.application.inverter_state import InverterState
from deye_inverter.application.planner_service import PlannerService
from deye_inverter.domain.manual import ManualCharge, ManualChargeError
from deye_inverter.domain.settings import Mode
from deye_inverter.ports import (
    Clock,
    JournalRepository,
    KeyValueStore,
    ReadingRepository,
    SettingsRepository,
)

KEY = "manual_charge"


class ManualChargeLockedError(ManualChargeError):
    """Manual charges run only while the automation is Live."""


class ManualChargeRepository:
    """The manual charge in force, kept in the key-value store."""

    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    def current(self) -> ManualCharge | None:
        raw = self._store.get(KEY)
        return ManualCharge.from_dict(json.loads(raw)) if raw else None

    def save(self, charge: ManualCharge) -> None:
        self._store.put(KEY, json.dumps(charge.as_dict()))

    def clear(self) -> None:
        self._store.put(KEY, "")


@dataclass(frozen=True)
class ManualChargeDependencies:
    """Parameter object for :class:`ManualChargeService`."""

    charges: ManualChargeRepository
    settings: SettingsRepository
    planner: PlannerService
    charging: ChargeSettingsService
    state: InverterState
    readings: ReadingRepository
    journal: JournalRepository
    clock: Clock


class ManualChargeService:
    def __init__(self, deps: ManualChargeDependencies) -> None:
        self._charges = deps.charges
        self._settings = deps.settings
        self._planner = deps.planner
        self._charging = deps.charging
        self._state = deps.state
        self._readings = deps.readings
        self._journal = deps.journal
        self._clock = deps.clock

    def current(self) -> ManualCharge | None:
        return self._charges.current()

    def start(
        self, target_soc: int, ready_time: time | None, hold_time: time | None
    ) -> dict[str, Any]:
        settings = self._settings.load()
        if settings.mode is not Mode.LIVE:
            raise ManualChargeLockedError("Manual charge works only in Live mode (Plan page)")
        now = self._clock.now()
        ready_at = _next(ready_time, now) if ready_time else None
        hold_until = _next_or_same(hold_time, ready_at or now) if hold_time else None
        max_hours = settings.tuning.manual_max_hours
        charge = ManualCharge(target_soc, now, ready_at, hold_until, max_hours=max_hours)
        latest = self._readings.latest()
        if ready_at is None and hold_until is None and latest and latest.battery_soc >= target_soc:
            raise ManualChargeError(f"The battery is already at {latest.battery_soc:.0f}%")
        charge = self._with_grid_switch_on(charge)
        self._charges.save(charge)
        self._log("started", charge)
        decision = self._planner.run("manual charge started")
        return {"charge": charge.as_dict(), "decision": decision.as_dict()}

    def cancel(self, reason: str = "cancelled", run_planner: bool = True) -> None:
        charge = self.current()
        if charge is None:
            return
        self._charges.clear()
        if charge.restore_grid_switch_off:
            self._charging.set_grid_charge(False)
        self._log(reason, charge)
        if run_planner and self._settings.load().mode is Mode.LIVE:
            self._planner.run("manual charge ended")

    def tick(self) -> None:
        """Ends a finished charge and keeps the inverter's table up to date."""
        charge = self.current()
        if charge is None:
            return
        if self._settings.load().mode is not Mode.LIVE:
            self.cancel("automation left Live", run_planner=False)
            return
        latest = self._readings.latest()
        soc = latest.battery_soc if latest else 0.0
        if charge.finished(self._clock.now(), soc):
            self.cancel("finished")
            return
        if self._planner.preview().status == "change":
            self._planner.run("manual charge")

    def status(self) -> dict[str, Any]:
        latest = self._readings.latest()
        switch = self._state.charge_settings()
        charge = self.current()
        return {
            "charge": charge.as_dict() if charge else None,
            "battery": {
                "soc": latest.battery_soc if latest else None,
                "power": latest.battery_power if latest else None,
                "at": latest.taken_at.isoformat() if latest else None,
            },
            "grid_charge_enabled": switch.grid_charge_enabled if switch else None,
            "mode": self._settings.load().mode.value,
        }

    def _with_grid_switch_on(self, charge: ManualCharge) -> ManualCharge:
        switch = self._state.charge_settings()
        if switch is None or switch.grid_charge_enabled:
            return charge
        outcome = self._charging.set_grid_charge(True)
        if outcome.status != "executed":
            raise ManualChargeError(f"Could not turn grid charge on: {outcome.message}")
        return replace(charge, restore_grid_switch_off=True)

    def _log(self, status: str, charge: ManualCharge) -> None:
        self._journal.add(
            SETTING,
            self._clock.now(),
            {"status": status, "reason": "manual charge", "message": _describe(charge)},
        )


def _next(moment: time, now: datetime) -> datetime:
    """The next occurrence of clock time ``moment`` after ``now``."""
    candidate = now.replace(hour=moment.hour, minute=moment.minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _next_or_same(moment: time, base: datetime) -> datetime:
    """The first occurrence of ``moment`` at or after ``base`` (same minute counts)."""
    candidate = base.replace(hour=moment.hour, minute=moment.minute, second=0, microsecond=0)
    if candidate.replace(second=base.second, microsecond=base.microsecond) == base:
        return base
    return candidate if candidate >= base else candidate + timedelta(days=1)


def _describe(charge: ManualCharge) -> str:
    start = f"by {charge.ready_at:%a %H:%M}" if charge.ready_at else "now"
    hold = f", held until {charge.hold_until:%a %H:%M}" if charge.hold_until else ""
    return f"charge to {charge.target_soc}% {start}{hold}"
