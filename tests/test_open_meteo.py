import httpx
import pytest

from deye_inverter.adapters.open_meteo import OpenMeteoForecast
from deye_inverter.domain.settings import SiteSettings
from deye_inverter.ports import GatewayError

URL = "https://forecast.example/v1/forecast"


def test_turns_irradiance_into_energy() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": ["2026-10-05T11:00", "2026-10-05T12:00", "2026-10-05T13:00"],
                    "global_tilted_irradiance": [500.0, None, 1000.0],
                    "temperature_2m": [8.5, 9.0, None],
                }
            },
        )

    provider = OpenMeteoForecast(
        URL, "Europe/Bucharest", httpx.Client(transport=httpx.MockTransport(handler))
    )
    forecast = provider.fetch(SiteSettings())
    assert [h.solar_kwh for h in forecast.hours] == pytest.approx([2.46, 4.92])
    assert [h.temperature for h in forecast.hours] == [8.5, None]
    assert seen["hourly"] == "global_tilted_irradiance,temperature_2m"
    assert seen["tilt"] == "28.0" and seen["azimuth"] == "0.0"
    assert forecast.hours[0].hour_end.utcoffset() is not None


def test_http_error() -> None:
    provider = OpenMeteoForecast(
        URL, "UTC", httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    )
    with pytest.raises(GatewayError):
        provider.fetch(SiteSettings())
