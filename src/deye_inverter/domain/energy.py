"""Energy balance of a day (or of any period, as a sum of days)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class EnergyBalance:
    """Energies in kWh.

    ``bought`` is energy taken from the grid; with zero export nothing is sold.
    What the house used that did not come from the grid came from the panels,
    directly or through the battery.
    """

    solar: float = 0.0
    consumption: float = 0.0
    bought: float = 0.0
    charged: float = 0.0
    discharged: float = 0.0

    @property
    def from_solar(self) -> float:
        return max(0.0, self.consumption - self.bought)

    @property
    def self_sufficiency(self) -> float | None:
        """Share of consumption covered without the grid, in percent."""
        if self.consumption <= 0:
            return None
        return self.from_solar / self.consumption * 100

    def __add__(self, other: EnergyBalance) -> EnergyBalance:
        return EnergyBalance(
            solar=self.solar + other.solar,
            consumption=self.consumption + other.consumption,
            bought=self.bought + other.bought,
            charged=self.charged + other.charged,
            discharged=self.discharged + other.discharged,
        )

    def as_dict(self) -> dict[str, Any]:
        sufficiency = self.self_sufficiency
        return {
            "solar": round(self.solar, 2),
            "consumption": round(self.consumption, 2),
            "from_solar": round(self.from_solar, 2),
            "from_grid": round(self.bought, 2),
            "charged": round(self.charged, 2),
            "discharged": round(self.discharged, 2),
            "self_sufficiency": None if sufficiency is None else round(sufficiency, 1),
        }


@dataclass(frozen=True)
class DailyEnergy:
    day: date
    balance: EnergyBalance
    source: str


def total(balances: Iterable[EnergyBalance]) -> EnergyBalance:
    result = EnergyBalance()
    for balance in balances:
        result = result + balance
    return result
