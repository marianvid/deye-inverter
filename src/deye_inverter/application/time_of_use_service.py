"""Sending a Time of Use table to the inverter (Command pattern: send → verify → log)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from deye_inverter.application.inverter_state import InverterState
from deye_inverter.domain.time_of_use import TimeOfUseTable, table_to_dicts
from deye_inverter.ports import (
    Clock,
    GatewayError,
    InverterGateway,
    JournalRepository,
    SettingsRepository,
)

COMMAND = "command"
ACCEPTED = ("executed", "mismatch")
RECENT_COMMANDS = 20


@dataclass(frozen=True)
class CommandOutcome:
    """Result of a command sent to the inverter: status (executed, mismatch, failed), message,
    whether the read-back matched, and the order id."""

    status: str
    message: str
    verified: bool
    order_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The outcome as a JSON-ready dict for the journal and the API."""
        return {
            "status": self.status,
            "message": self.message,
            "verified": self.verified,
            "order_id": self.order_id,
        }


@dataclass(frozen=True)
class TimeOfUseDependencies:
    """Parameter object for :class:`TimeOfUseService`."""

    gateway: InverterGateway
    state: InverterState
    journal: JournalRepository
    clock: Clock
    settings: SettingsRepository
    sleep: Callable[[float], None] = time.sleep


class TimeOfUseService:
    """Writes a time-of-use table to the inverter, reads it back to verify and journals the
    command."""

    def __init__(self, deps: TimeOfUseDependencies) -> None:
        self._sleep = deps.sleep
        self._settings = deps.settings
        self._gateway = deps.gateway
        self._state = deps.state
        self._journal = deps.journal
        self._clock = deps.clock

    def send(self, table: TimeOfUseTable, reason: str) -> CommandOutcome:
        """Writes the table to the inverter, verifies it by reading back and journals the command
        with its reason."""
        started = self._clock.now()
        try:
            outcome = self._send_and_verify(table)
        except GatewayError as error:
            outcome = CommandOutcome("failed", str(error), verified=False)
        entry = {**outcome.as_dict(), "reason": reason, "slots": table_to_dicts(table)}
        self._journal.add(COMMAND, started, entry)
        return outcome

    def last_write_at(self) -> datetime | None:
        """When the inverter last accepted a table (verified or not)."""
        for entry in self._journal.recent(COMMAND, RECENT_COMMANDS):
            if entry.get("status") in ACCEPTED:
                return datetime.fromisoformat(str(entry["at"]))
        return None

    def writes_today(self) -> int:
        """Tables the inverter accepted today, verified or not."""
        midnight = self._clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return sum(self._journal.count_since(COMMAND, midnight, s) for s in ACCEPTED)

    def _send_and_verify(self, table: TimeOfUseTable) -> CommandOutcome:
        result = self._gateway.write_time_of_use(table)
        if not result.accepted:
            return CommandOutcome("failed", result.message, False, result.order_id)
        read_back = self._read_back(table)
        self._state.remember_current_table(read_back, self._clock.now())
        verified = read_back == table
        status = "executed" if verified else "mismatch"
        message = "applied and verified" if verified else "inverter table differs after write"
        return CommandOutcome(status, message, verified, result.order_id)

    def _read_back(self, expected: TimeOfUseTable) -> TimeOfUseTable:
        """DeyeCloud shows a new table only after a while: read again a few times."""
        tuning = self._settings.load().tuning
        read_back = self._gateway.read_time_of_use()
        for _ in range(tuning.verify_attempts - 1):
            if read_back == expected:
                break
            self._sleep(tuning.verify_pause_seconds)
            read_back = self._gateway.read_time_of_use()
        return read_back
