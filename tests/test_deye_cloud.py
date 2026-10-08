import json
from typing import Any

import httpx
import pytest

from deye_inverter.adapters.deye_cloud import (
    DeyeCloudClient,
    DeyeCloudGateway,
    TimeOfUseCodec,
)
from deye_inverter.config import Credentials
from deye_inverter.ports import GatewayError
from tests.fakes import winter_table

CREDENTIALS = Credentials("app", "secret", "a@b", "hash")
TOU_ITEMS = [
    {
        "time": f"{h:02d}00",
        "soc": 75 if h == 13 else 55,
        "power": 8000,
        "voltage": 50,
        "enableGridCharge": True,
        "enableGeneration": False,
    }
    for h in (1, 5, 9, 13, 17, 21)
]


class FakeCloud:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.order_statuses = ["100", "666"]
        self.token_requests = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        body = json.loads(request.content) if request.content else None
        self.calls.append((path, body))
        return httpx.Response(200, json=self._answer(path))

    def _answer(self, path: str) -> dict[str, Any]:
        ok = {"code": "1000000", "msg": "success"}
        if path == "/account/token":
            self.token_requests += 1
            return {**ok, "accessToken": "bearer T", "expiresIn": 200000}
        if path == "/station/listWithDevice":
            return {
                **ok,
                "stationList": [
                    {
                        "deviceListItems": [
                            {"deviceType": "COLLECTOR", "deviceSn": "L1"},
                            {"deviceType": "INVERTER", "deviceSn": "INV1"},
                        ]
                    }
                ],
            }
        if path == "/device/latest":
            return {
                **ok,
                "deviceDataList": [
                    {
                        "collectionTime": 1791194419,
                        "dataList": [
                            {"key": "SOC", "value": "99"},
                            {"key": "TotalDCInputPower", "value": "1011.00"},
                            {"key": "Temperature- Battery", "value": "26.5"},
                            {"key": "BatteryPower", "value": "x"},
                        ],
                    }
                ],
            }
        if path == "/config/tou":
            return {**ok, "timeUseSettingItems": TOU_ITEMS}
        if path == "/config/battery":
            return {
                **ok,
                "maxChargeCurrent": 100,
                "battShutDownCapacity": 20,
                "battLowCapacity": 30,
                "battCapacity": 315,
            }
        if path == "/order/sys/tou/update":
            return {"code": "1106000", "msg": "order sent", "orderId": 77}
        if path == "/order/77":
            return {**ok, "status": self.order_statuses.pop(0)}
        return {"code": "9", "msg": "unknown path"}


def gateway(cloud: FakeCloud) -> DeyeCloudGateway:
    http = httpx.Client(transport=httpx.MockTransport(cloud.handle))
    client = DeyeCloudClient("https://cloud.test/v1.0", CREDENTIALS, http)
    return DeyeCloudGateway(client, sleep=lambda _: None)


def test_discovers_inverter_and_reads_live_values() -> None:
    cloud = FakeCloud()
    reading = gateway(cloud).read_live()
    assert reading.battery_soc == 99
    assert reading.solar_power == 1011
    assert reading.battery_power == 0.0
    assert reading.battery_temperature == 26.5
    assert cloud.calls[1] == ("/station/listWithDevice", {"page": 1, "size": 10})
    assert cloud.token_requests == 1


def test_reads_time_of_use_and_battery_settings() -> None:
    target = gateway(FakeCloud())
    assert target.read_time_of_use() == winter_table()
    assert target.read_battery_settings().max_charge_current == 100


def test_write_waits_for_order_status() -> None:
    cloud = FakeCloud()
    result = gateway(cloud).write_time_of_use(winter_table())
    assert result.accepted and result.status == "666" and result.order_id == "77"
    sent = next(body for path, body in cloud.calls if path == "/order/sys/tou/update")
    assert sent["timeUseSettingItems"][0]["time"] == "01:00"


def test_failed_order_is_reported() -> None:
    cloud = FakeCloud()
    cloud.order_statuses = ["500"]
    result = gateway(cloud).write_time_of_use(winter_table())
    assert not result.accepted and "500" in result.message


def test_errors_raise_gateway_error() -> None:
    def broken(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = DeyeCloudClient(
        "https://x/v1.0", CREDENTIALS, httpx.Client(transport=httpx.MockTransport(broken))
    )
    with pytest.raises(GatewayError):
        client.post("/config/tou", {})

    def refused(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "2101017", "msg": "bad password"})

    client = DeyeCloudClient(
        "https://x/v1.0", CREDENTIALS, httpx.Client(transport=httpx.MockTransport(refused))
    )
    with pytest.raises(GatewayError, match="bad password"):
        client.get("/order/1")


def test_codec_accepts_both_time_formats() -> None:
    codec = TimeOfUseCodec()
    items = [dict(item, time=f"{item['time'][:2]}:{item['time'][2:]}") for item in TOU_ITEMS]
    assert codec.decode(items) == codec.decode(TOU_ITEMS)


def test_reads_charge_settings_through_a_read_order() -> None:
    cloud = FakeCloud()
    registers = {
        "00E6": "60",
        "00E8": "1",
        "00F4": "2",
        "00F8": "255",
        "00D2": "100",
        "00D3": "190",
    }

    def answer(path: str) -> dict[str, Any]:
        ok = {"code": "1000000", "msg": "success"}
        if path == "/strategy/dynamicControl/read":
            return {"code": "1106000", "orderId": 88}
        if path == "/order/88":
            return {**ok, "status": 666, "analysisResult": json.dumps(registers)}
        return FakeCloud._answer(cloud, path)

    cloud._answer = answer  # type: ignore[method-assign]
    settings = gateway(cloud).read_charge_settings()
    assert settings.grid_charge_enabled and settings.grid_charge_current == 60
    assert settings.time_of_use_enabled and settings.work_mode == "Zero export to CT"
    registers["00F4"] = "7"
    registers["00E8"] = "0"
    other = gateway(cloud).read_charge_settings()
    assert other.work_mode == "mode 7" and not other.grid_charge_enabled
    del registers["00E6"]
    with pytest.raises(GatewayError, match="00E6"):
        gateway(cloud).read_charge_settings()


def test_read_order_failures() -> None:
    cloud = FakeCloud()

    def answer(path: str) -> dict[str, Any]:
        if path == "/strategy/dynamicControl/read":
            return {"code": "1106000"}
        return FakeCloud._answer(cloud, path)

    cloud._answer = answer  # type: ignore[method-assign]
    with pytest.raises(GatewayError, match="no order id"):
        gateway(cloud).read_charge_settings()

    def failed(path: str) -> dict[str, Any]:
        if path == "/strategy/dynamicControl/read":
            return {"code": "1106000", "orderId": 9}
        if path == "/order/9":
            return {"code": "1000000", "status": 500}
        return FakeCloud._answer(cloud, path)

    cloud._answer = failed  # type: ignore[method-assign]
    with pytest.raises(GatewayError, match="status 500"):
        gateway(cloud).read_charge_settings()


def test_grid_charge_mode_control() -> None:
    cloud = FakeCloud()

    def answer(path: str) -> dict[str, Any]:
        if path == "/order/battery/modeControl":
            return {"code": "1106000", "orderId": 77}
        return FakeCloud._answer(cloud, path)

    cloud._answer = answer  # type: ignore[method-assign]
    assert gateway(cloud).set_grid_charge(False).accepted
    body = next(b for p, b in cloud.calls if p == "/order/battery/modeControl")
    assert body == {"deviceSn": "INV1", "batteryModeType": "GRID_CHARGE", "action": "off"}

    def no_order(path: str) -> dict[str, Any]:
        if path == "/order/battery/modeControl":
            return {"code": "1106000"}
        return FakeCloud._answer(cloud, path)

    cloud._answer = no_order  # type: ignore[method-assign]
    with pytest.raises(GatewayError):
        gateway(cloud).set_grid_charge(True)
