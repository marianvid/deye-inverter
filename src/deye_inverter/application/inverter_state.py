"""What the application knows about the inverter's settings, kept in the store."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from deye_inverter.domain.readings import BatterySettings, ChargeSettings
from deye_inverter.domain.time_of_use import TimeOfUseTable, table_from_dicts, table_to_dicts
from deye_inverter.ports import KeyValueStore

CURRENT_TABLE = "inverter_time_of_use"
BASE_TABLE = "base_time_of_use"
BATTERY = "inverter_battery_settings"
CHARGE = "inverter_charge_settings"


class InverterState:
    """Last Time of Use table and battery settings read from the inverter, and the
    base table the owner keeps (the table the planner starts from)."""

    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    def current_table(self) -> TimeOfUseTable | None:
        return self._table(CURRENT_TABLE)

    def current_table_read_at(self) -> str | None:
        stored = self._load(CURRENT_TABLE)
        return str(stored["read_at"]) if stored else None

    def remember_current_table(self, table: TimeOfUseTable, read_at: datetime) -> None:
        self._save(CURRENT_TABLE, {"read_at": read_at.isoformat(), "slots": table_to_dicts(table)})
        if self.base_table() is None:
            self.save_base_table(table, read_at)

    def base_table(self) -> TimeOfUseTable | None:
        return self._table(BASE_TABLE)

    def save_base_table(self, table: TimeOfUseTable, saved_at: datetime) -> None:
        self._save(BASE_TABLE, {"read_at": saved_at.isoformat(), "slots": table_to_dicts(table)})

    def battery_settings(self) -> BatterySettings | None:
        stored = self._load(BATTERY)
        return BatterySettings(**stored["settings"]) if stored else None

    def remember_battery_settings(self, settings: BatterySettings, read_at: datetime) -> None:
        self._save(BATTERY, {"read_at": read_at.isoformat(), "settings": asdict(settings)})

    def charge_settings(self) -> ChargeSettings | None:
        stored = self._load(CHARGE)
        return ChargeSettings(**stored["settings"]) if stored else None

    def charge_settings_read_at(self) -> str | None:
        stored = self._load(CHARGE)
        return str(stored["read_at"]) if stored else None

    def remember_charge_settings(self, settings: ChargeSettings, read_at: datetime) -> None:
        self._save(CHARGE, {"read_at": read_at.isoformat(), "settings": asdict(settings)})

    def _table(self, key: str) -> TimeOfUseTable | None:
        stored = self._load(key)
        return table_from_dicts(stored["slots"]) if stored else None

    def _load(self, key: str) -> dict[str, Any] | None:
        raw = self._store.get(key)
        return dict(json.loads(raw)) if raw else None

    def _save(self, key: str, value: dict[str, Any]) -> None:
        self._store.put(key, json.dumps(value))
