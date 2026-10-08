"""Settings the owner edits in the interface, with the shipped defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, time
from enum import StrEnum
from typing import Any


class Mode(StrEnum):
    OFF = "off"
    DRY_RUN = "dry-run"
    LIVE = "live"


DAY_MINUTES = 24 * 60
ALL_DAYS = (0, 1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class ReserveSettings:
    """Outage reserve: from ``protect_from`` until ``protect_until`` the battery keeps
    what a grid outage would need until the panels take over again.

    The protected moments are ``protect_from`` and every slot start after it, before
    ``protect_until``. For each, an hour-by-hour simulation of an outage gives the
    lowest SOC that carries the house through; that SOC is the slot's floor.
    """

    enabled: bool = True
    protect_from: time = time(16, 0)
    protect_until: time = time(9, 0)
    weekdays: tuple[int, ...] = ALL_DAYS
    skip_dates: tuple[date, ...] = ()
    # Essential house load during an outage (kW) by part of the day.
    evening_kw: float = 0.9
    evening_until: time = time(20, 0)
    late_evening_kw: float = 0.4
    late_evening_until: time = time(22, 0)
    morning_kw: float = 1.0
    morning_from: time = time(6, 0)
    morning_until: time = time(9, 0)
    # Any other hour: the night load from history, with a margin, at most this much.
    night_margin: float = 1.25
    night_cap_kw: float = 0.5
    # Share of the solar forecast counted on during an outage.
    solar_factor: float = 0.5
    max_soc: int = 90
    # With a generator the battery only has to bridge until the generator runs.
    generator_available: bool = False
    generator_bridge_hours: float = 1.0

    def applies_on(self, day: date) -> bool:
        return self.enabled and day.weekday() in self.weekdays and day not in self.skip_dates


@dataclass(frozen=True)
class FloorSettings:
    """Every slot the reserve does not set lets the battery run down to ``soc``."""

    soc: int = 30
    grid_charge: bool = False


@dataclass(frozen=True)
class SiteSettings:
    # The real location comes from the private configuration (opts), see SiteConfig.
    latitude: float = 0.0
    longitude: float = 0.0
    panel_kwp: float = 6.0
    panel_tilt: float = 28.0
    panel_azimuth: float = 0.0
    performance_ratio: float = 0.82
    battery_kwh: float = 16.0
    battery_nominal_voltage: float = 51.2
    min_soc: int = 20
    consumption_days: int = 7
    fallback_load_kw: float = 0.6


@dataclass(frozen=True)
class TuningSettings:
    """How the planner computes and writes; rarely changed."""

    check_every_minutes: int = 15
    # Grid charging starts this much earlier than the bare estimate (losses, taper).
    charge_margin: float = 1.2
    start_step_minutes: int = 5
    # A planned grid charging start on the inverter moves only beyond this.
    start_tolerance_minutes: int = 15
    # A reserve on the inverter is rewritten only when the new one differs more.
    soc_tolerance: int = 3
    # Today's actual / forecast solar ratio corrects the forecast, within these bounds.
    solar_ratio_min: float = 0.2
    solar_ratio_max: float = 1.5
    min_forecast_for_ratio_kwh: float = 0.5
    # Grid charging power when the inverter's charge settings are unknown.
    fallback_charge_kw: float = 3.0
    manual_max_hours: int = 48
    verify_attempts: int = 4
    verify_pause_seconds: float = 15.0

    def check_times(self) -> tuple[time, ...]:
        step = max(5, self.check_every_minutes)
        return tuple(time(m // 60, m % 60) for m in range(0, DAY_MINUTES, step))


@dataclass(frozen=True)
class PlannerSettings:
    mode: Mode = Mode.DRY_RUN
    max_writes_per_day: int = 6
    reserve: ReserveSettings = field(default_factory=ReserveSettings)
    floor: FloorSettings = field(default_factory=FloorSettings)
    site: SiteSettings = field(default_factory=SiteSettings)
    tuning: TuningSettings = field(default_factory=TuningSettings)


class SettingsCodec:
    """Converts :class:`PlannerSettings` to and from plain JSON-ready values.

    Missing values take ``defaults`` (the shipped defaults plus the configured site).
    """

    def __init__(self, defaults: PlannerSettings | None = None) -> None:
        self.defaults = defaults or PlannerSettings()

    def to_dict(self, settings: PlannerSettings) -> dict[str, Any]:
        encoded: dict[str, Any] = _encode(asdict(settings))
        return encoded

    def from_dict(self, data: dict[str, Any]) -> PlannerSettings:
        defaults = self.defaults
        return PlannerSettings(
            mode=Mode(data.get("mode", defaults.mode)),
            max_writes_per_day=int(data.get("max_writes_per_day", defaults.max_writes_per_day)),
            reserve=_build(defaults.reserve, data.get("reserve", {})),
            floor=_build(defaults.floor, data.get("floor", {})),
            site=_build(defaults.site, data.get("site", {})),
            tuning=_build(defaults.tuning, data.get("tuning", {})),
        )


def _encode(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _build[T](default: T, data: dict[str, Any]) -> T:
    cls = type(default)
    values = {}
    for item in fields(cls):  # type: ignore[arg-type]
        current = getattr(default, item.name)
        values[item.name] = _decode(data[item.name], current) if item.name in data else current
    return cls(**values)


def _decode(value: Any, like: Any) -> Any:
    if isinstance(like, bool):
        return bool(value)
    if isinstance(like, int):
        return int(value)
    if isinstance(like, float):
        return float(value)
    if isinstance(like, time):
        return time.fromisoformat(str(value))
    if isinstance(like, tuple):
        return _decode_sequence(value, like)
    return value


def _decode_sequence(value: Any, like: tuple[Any, ...]) -> tuple[Any, ...]:
    items = list(value or [])
    if like:
        return tuple(_decode(v, like[0]) for v in items)
    return tuple(date.fromisoformat(str(v)) for v in items)
