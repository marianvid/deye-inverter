"""Changing the inverter's charging settings (send → read back → log)."""

from __future__ import annotations

from deye_inverter.application.inverter_state import InverterState
from deye_inverter.application.time_of_use_service import CommandOutcome
from deye_inverter.ports import Clock, GatewayError, InverterGateway, JournalRepository

SETTING = "setting"


class ChargeSettingsService:
    def __init__(
        self,
        gateway: InverterGateway,
        state: InverterState,
        journal: JournalRepository,
        clock: Clock,
    ) -> None:
        self._gateway = gateway
        self._state = state
        self._journal = journal
        self._clock = clock

    def set_grid_charge(self, enabled: bool) -> CommandOutcome:
        started = self._clock.now()
        try:
            outcome = self._apply(enabled)
        except GatewayError as error:
            outcome = CommandOutcome("failed", str(error), verified=False)
        label = "on" if enabled else "off"
        self._journal.add(SETTING, started, {**outcome.as_dict(), "reason": f"grid charge {label}"})
        return outcome

    def _apply(self, enabled: bool) -> CommandOutcome:
        result = self._gateway.set_grid_charge(enabled)
        if not result.accepted:
            return CommandOutcome("failed", result.message, False, result.order_id)
        settings = self._gateway.read_charge_settings()
        self._state.remember_charge_settings(settings, self._clock.now())
        verified = settings.grid_charge_enabled == enabled
        status = "executed" if verified else "mismatch"
        message = "applied and verified" if verified else "inverter reports another value"
        return CommandOutcome(status, message, verified, result.order_id)
