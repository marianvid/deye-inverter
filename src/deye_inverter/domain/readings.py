"""Measurements and settings read from the inverter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Reading:
    """One snapshot of the inverter's live values (powers in W, energies in kWh)."""

    taken_at: datetime
    solar_power: float
    load_power: float
    backup_load_power: float
    grid_power: float
    battery_power: float
    battery_soc: float
    battery_voltage: float
    solar_today: float
    load_today: float
    grid_bought_today: float
    battery_charged_today: float
    battery_discharged_today: float
    battery_temperature: float | None = None
    raw: dict[str, str] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class BatterySettings:
    """Battery settings as configured in the inverter (read only)."""

    max_charge_current: float
    shutdown_soc: int
    low_soc: int
    capacity_ah: int


@dataclass(frozen=True)
class ChargeSettings:
    """How the inverter is allowed to charge the battery (read only).

    ``grid_charge_enabled`` is the master switch: per-slot grid charging in the
    Time of Use table works only when it is on. ``grid_charge_current`` limits
    how fast the grid charges the battery.
    """

    grid_charge_enabled: bool
    grid_charge_current: int
    time_of_use_enabled: bool
    work_mode: str
    max_charge_current: int
    max_discharge_current: int


def reading_as_dict(reading: Reading) -> dict[str, Any]:
    """JSON-ready form without the raw cloud values."""
    data = asdict(reading)
    data["taken_at"] = reading.taken_at.isoformat()
    data.pop("raw", None)
    return data
