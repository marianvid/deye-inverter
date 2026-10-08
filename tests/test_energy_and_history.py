import json
from datetime import date
from typing import Any

import httpx
import pytest

from deye_inverter.adapters.deye_cloud import DeyeCloudClient
from deye_inverter.adapters.deye_cloud_history import DeyeCloudHistory
from deye_inverter.application.statistics import Period
from deye_inverter.config import Credentials
from deye_inverter.domain.energy import EnergyBalance, total
from deye_inverter.ports import GatewayError
from tests.fakes import at, reading


def test_energy_balance_arithmetic() -> None:
    day = EnergyBalance(solar=10, consumption=8, bought=2, charged=3, discharged=3)
    assert day.from_solar == 6 and day.self_sufficiency == 75
    both = total([day, day])
    assert both.consumption == 16 and both.as_dict()["from_grid"] == 4
    assert EnergyBalance().self_sufficiency is None
    assert EnergyBalance(consumption=1, bought=2).from_solar == 0


class FakeStationCloud:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        ok = {"code": "1000000", "msg": "success"}
        if path == "/account/token":
            return httpx.Response(200, json={**ok, "accessToken": "T", "expiresIn": 999999})
        body = json.loads(request.content)
        if path == "/station/list":
            return httpx.Response(
                200, json={**ok, "stationList": [{"id": 7, "startOperatingTime": 1781300168}]}
            )
        self.bodies.append(body)
        if body["granularity"] == 2:
            items = [
                {
                    "year": 2026,
                    "month": 6,
                    "day": 12,
                    "generationValue": 5.0,
                    "consumptionValue": 6.0,
                    "purchaseValue": 1.0,
                    "chargeValue": None,
                    "dischargeValue": 2.0,
                }
            ]
            return httpx.Response(200, json={**ok, "stationDataItems": items})
        items = [
            {"timeStamp": 1781300400, "generationPower": 100.0, "batterySOC": 80.0},
            {"timeStamp": None},
        ]
        return httpx.Response(200, json={**ok, "stationDataItems": items})


def history(cloud: FakeStationCloud) -> DeyeCloudHistory:
    http = httpx.Client(transport=httpx.MockTransport(cloud.handle))
    client = DeyeCloudClient("https://x/v1.0", Credentials("a", "s", "e", "p"), http)
    return DeyeCloudHistory(client, "Europe/Bucharest")


def test_cloud_history_daily_in_chunks_and_frames() -> None:
    cloud = FakeStationCloud()
    source = history(cloud)
    assert source.first_day() == date(2026, 6, 13)
    records = source.daily(date(2026, 6, 12), date(2026, 8, 20))
    assert len(cloud.bodies) == 3
    assert cloud.bodies[0] == {
        "stationId": "7",
        "granularity": 2,
        "startAt": "2026-06-12",
        "endAt": "2026-07-12",
    }
    assert records[0].balance.consumption == 6 and records[0].balance.charged == 0
    frames = source.frames(date(2026, 6, 12))
    assert len(frames) == 1 and frames[0].solar_power == 100 and frames[0].battery_soc == 80
    assert cloud.bodies[-1]["endAt"] == "2026-06-13"


def test_cloud_history_errors() -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/account/token"):
            return httpx.Response(200, json={"code": "0", "accessToken": "T"})
        return httpx.Response(200, json={"code": "0", "stationList": [{"id": 9}]})

    client = DeyeCloudClient(
        "https://x/v1.0",
        Credentials("a", "s", "e", "p"),
        httpx.Client(transport=httpx.MockTransport(empty)),
    )
    with pytest.raises(GatewayError):
        DeyeCloudHistory(client, "UTC").first_day()

    def none(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/account/token"):
            return httpx.Response(200, json={"code": "0", "accessToken": "T"})
        return httpx.Response(200, json={"code": "0", "stationList": []})

    client = DeyeCloudClient(
        "https://x/v1.0",
        Credentials("a", "s", "e", "p"),
        httpx.Client(transport=httpx.MockTransport(none)),
    )
    with pytest.raises(GatewayError):
        _ = DeyeCloudHistory(client, "UTC").station_id


def test_sync_daily_full_then_recent(world) -> None:
    world.services.sync_daily()
    assert world.history.daily_calls == [(date(2026, 10, 1), date(2026, 10, 4))]
    world.clock.moment = at(10, day=20)
    world.services.sync_daily()
    assert world.history.daily_calls[-1] == (date(2026, 10, 1), date(2026, 10, 19))
    world.history.first = date(2026, 10, 25)
    world.services.sync_daily()
    assert len(world.history.daily_calls) == 2


def test_record_today_and_backfill(world, primed) -> None:
    world.services.record_today()
    primed()
    world.services.record_today()
    stats = world.services.statistics.summary(Period.DAY)
    assert stats["totals"]["consumption"] == 5.0
    first = world.services.backfill()
    assert first == {"filled": 4, "remaining": 0}
    assert world.history.frame_calls == [
        date(2026, 10, 4),
        date(2026, 10, 3),
        date(2026, 10, 2),
        date(2026, 10, 1),
    ]
    assert world.services.backfill() == {"filled": 0, "remaining": 0}


def test_record_today_uses_local_day(world) -> None:
    world.gateway.live = reading(at(0, 2), solar_today=0.0)
    world.services.collect_readings()
    world.services.record_today()
    assert world.services.statistics.summary(Period.DAY)["days_with_data"] == 1


def test_backfill_retries_a_refused_day_then_gives_up(world) -> None:
    world.history.failing = {date(2026, 10, 3)}
    assert world.services.backfill() == {"filled": 1, "remaining": 3}
    assert world.services.backfill() == {"filled": 0, "remaining": 3}
    world.history.failing = set()
    assert world.services.backfill() == {"filled": 3, "remaining": 0}
