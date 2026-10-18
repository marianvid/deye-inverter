"""Jobs that copy data from the outside world into the local database."""

from __future__ import annotations

from deye_inverter.application.inverter_state import InverterState
from deye_inverter.ports import (
    Clock,
    ForecastProvider,
    ForecastRepository,
    InverterGateway,
    ReadingRepository,
    SettingsRepository,
)


class CollectReadings:
    """Job that stores one live reading (power flows, battery SOC, day counters) from the
    inverter."""

    def __init__(self, gateway: InverterGateway, readings: ReadingRepository) -> None:
        self._gateway = gateway
        self._readings = readings

    def __call__(self) -> None:
        self._readings.add(self._gateway.read_live())


class RefreshInverterSettings:
    """Job that reads the time-of-use table, battery settings and charge settings from the inverter
    and remembers them."""

    def __init__(self, gateway: InverterGateway, state: InverterState, clock: Clock) -> None:
        self._gateway = gateway
        self._state = state
        self._clock = clock

    def __call__(self) -> None:
        now = self._clock.now()
        self._state.remember_current_table(self._gateway.read_time_of_use(), now)
        self._state.remember_battery_settings(self._gateway.read_battery_settings(), now)
        self._state.remember_charge_settings(self._gateway.read_charge_settings(), now)


class RefreshForecast:
    """Job that fetches the solar forecast for the configured site and stores it."""

    def __init__(
        self,
        provider: ForecastProvider,
        forecasts: ForecastRepository,
        settings: SettingsRepository,
        clock: Clock,
    ) -> None:
        self._provider = provider
        self._forecasts = forecasts
        self._settings = settings
        self._clock = clock

    def __call__(self) -> None:
        forecast = self._provider.fetch(self._settings.load().site)
        self._forecasts.save(forecast, self._clock.now())
