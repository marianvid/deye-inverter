"""Open-Meteo adapter: solar irradiance on the panel plane, turned into kWh."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from deye_inverter.domain.forecast import Forecast, ForecastHour
from deye_inverter.domain.settings import SiteSettings
from deye_inverter.ports import ForecastProvider, GatewayError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
STANDARD_IRRADIANCE = 1000.0  # W/m² at which panels deliver their rated kWp


class OpenMeteoForecast(ForecastProvider):
    """Hourly ``global_tilted_irradiance`` (mean over the preceding hour)."""

    def __init__(self, timezone: str, http: httpx.Client | None = None, days: int = 3) -> None:
        self._zone = ZoneInfo(timezone)
        self._timezone = timezone
        self._http = http or httpx.Client(timeout=30)
        self._days = days

    def fetch(self, site: SiteSettings) -> Forecast:
        response = self._http.get(FORECAST_URL, params=self._params(site))
        if response.status_code >= 400:
            raise GatewayError(f"Open-Meteo: HTTP {response.status_code}")
        return self._parse(response.json(), site)

    def _params(self, site: SiteSettings) -> dict[str, Any]:
        return {
            "latitude": site.latitude,
            "longitude": site.longitude,
            "hourly": "global_tilted_irradiance",
            "tilt": site.panel_tilt,
            "azimuth": site.panel_azimuth,
            "timezone": self._timezone,
            "past_days": 1,
            "forecast_days": self._days,
        }

    def _parse(self, data: dict[str, Any], site: SiteSettings) -> Forecast:
        hourly = data.get("hourly") or {}
        stamps = hourly.get("time") or []
        values = hourly.get("global_tilted_irradiance") or []
        hours = []
        for stamp, irradiance in zip(stamps, values, strict=False):
            if irradiance is None:
                continue
            hour_end = datetime.fromisoformat(stamp).replace(tzinfo=self._zone)
            kwh = irradiance / STANDARD_IRRADIANCE * site.panel_kwp * site.performance_ratio
            hours.append(ForecastHour(hour_end, float(irradiance), kwh))
        return Forecast.of(hours)
