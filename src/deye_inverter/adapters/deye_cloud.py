"""DeyeCloud OpenAPI adapter: implements :class:`InverterGateway` over HTTPS."""

from __future__ import annotations

import json
import threading
import time as systime
from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Any, ClassVar

import httpx

from deye_inverter.config import Credentials
from deye_inverter.domain.readings import BatterySettings, ChargeSettings, Reading
from deye_inverter.domain.time_of_use import TimeOfUseSlot, TimeOfUseTable
from deye_inverter.ports import GatewayError, InverterGateway, WriteResult

SUCCESS_CODES = {"0", "1000000", "1106000"}
ORDER_DONE = "666"
ORDER_PENDING = {"0", "100"}
TOKEN_MARGIN_SECONDS = 86_400
DEFAULT_TOKEN_LIFETIME = 60 * 24 * 3600


class DeyeCloudClient:
    """Thin HTTP client: token handling, JSON calls, response checks."""

    def __init__(
        self,
        base_url: str,
        credentials: Credentials,
        http: httpx.Client | None = None,
        monotonic: Callable[[], float] = systime.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._http = http or httpx.Client(timeout=30)
        self._monotonic = monotonic
        self._token: str | None = None
        self._token_expiry = 0.0
        self._token_lock = threading.Lock()

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", path, body)

    def get(self, path: str) -> dict[str, Any]:
        return self._call("GET", path, None)

    def _call(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._valid_token()}"}
        response = self._http.request(method, self._base_url + path, json=body, headers=headers)
        return self._checked(response, path)

    def _valid_token(self) -> str:
        with self._token_lock:
            if self._token is None or self._monotonic() >= self._token_expiry:
                self._token = self._obtain_token()
            return self._token

    def _obtain_token(self) -> str:
        body = {
            "appSecret": self._credentials.app_secret,
            "email": self._credentials.email,
            "password": self._credentials.password_sha256,
        }
        url = f"{self._base_url}/account/token?appId={self._credentials.app_id}"
        data = self._checked(self._http.post(url, json=body), "/account/token")
        token = str(data.get("accessToken") or "").split(" ")[-1]
        if not token:
            raise GatewayError("DeyeCloud returned no access token")
        lifetime = float(data.get("expiresIn") or DEFAULT_TOKEN_LIFETIME)
        self._token_expiry = self._monotonic() + lifetime - TOKEN_MARGIN_SECONDS
        return token

    @staticmethod
    def _checked(response: httpx.Response, path: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise GatewayError(f"DeyeCloud {path}: HTTP {response.status_code}")
        data: dict[str, Any] = response.json()
        if str(data.get("code")) not in SUCCESS_CODES:
            raise GatewayError(f"DeyeCloud {path}: {data.get('msg')} (code {data.get('code')})")
        return data


class TimeOfUseCodec:
    """Maps DeyeCloud ``timeUseSettingItems`` to the domain table and back."""

    def decode(self, items: list[dict[str, Any]]) -> TimeOfUseTable:
        return TimeOfUseTable(tuple(self._slot(item) for item in items))

    def encode(self, table: TimeOfUseTable) -> list[dict[str, Any]]:
        return [
            {
                "time": slot.start.strftime("%H:%M"),
                "soc": slot.soc,
                "power": slot.power,
                "voltage": slot.voltage,
                "enableGridCharge": slot.grid_charge,
                "enableGeneration": slot.generator_charge,
            }
            for slot in table
        ]

    @staticmethod
    def _slot(item: dict[str, Any]) -> TimeOfUseSlot:
        return TimeOfUseSlot(
            start=_parse_slot_time(str(item["time"])),
            soc=int(item["soc"]),
            power=int(item["power"]),
            voltage=float(item.get("voltage", 0)),
            grid_charge=bool(item.get("enableGridCharge")),
            generator_charge=bool(item.get("enableGeneration")),
        )


def _parse_slot_time(value: str) -> time:
    if ":" in value:
        hours, minutes = value.split(":", 1)
    else:
        digits = value.zfill(4)
        hours, minutes = digits[:2], digits[2:]
    return time(int(hours), int(minutes))


class ReadingMapper:
    """Maps a DeyeCloud ``dataList`` to a :class:`Reading`."""

    FIELDS: ClassVar[dict[str, str]] = {
        "solar_power": "TotalDCInputPower",
        "load_power": "TotalConsumptionPower",
        "backup_load_power": "UPSLoadPower",
        "grid_power": "TotalGridPower",
        "battery_power": "BatteryPower",
        "battery_soc": "SOC",
        "battery_voltage": "BatteryVoltage",
        "solar_today": "PVDailyPowerGenerationActive",
        "load_today": "DailyConsumption",
        "grid_bought_today": "DailyEnergyPurchased",
        "battery_charged_today": "DailyChargingEnergy",
        "battery_discharged_today": "DailyDischargingEnergy",
    }
    TEMPERATURE = "Temperature- Battery"

    def map(self, device: dict[str, Any]) -> Reading:
        raw = {str(i.get("key")): str(i.get("value")) for i in device.get("dataList", [])}
        values = {name: _number(raw.get(key)) for name, key in self.FIELDS.items()}
        taken_at = datetime.fromtimestamp(float(device.get("collectionTime") or 0), tz=UTC)
        temperature = raw.get(self.TEMPERATURE)
        return Reading(
            taken_at=taken_at,
            battery_temperature=_number(temperature) if temperature is not None else None,
            raw=raw,
            **values,
        )


def _number(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


class ChargeSettingsMapper:
    """Maps Deye hybrid holding registers (hex address -> value) to :class:`ChargeSettings`."""

    GRID_CHARGE_CURRENT = "00E6"  # 230: grid charge current, A
    GRID_CHARGE_ENABLED = "00E8"  # 232: grid charge master switch
    WORK_MODE = "00F4"  # 244: system work mode
    TOU_DAYS = "00F8"  # 248: Time of Use enable + weekday bits
    MAX_CHARGE = "00D2"  # 210: battery max charge current, A
    MAX_DISCHARGE = "00D3"  # 211: battery max discharge current, A
    WORK_MODES: ClassVar[dict[int, str]] = {
        0: "Selling first",
        1: "Zero export to load",
        2: "Zero export to CT",
    }

    def map(self, registers: dict[str, Any]) -> ChargeSettings:
        value = _register_reader(registers)
        mode = value(self.WORK_MODE)
        return ChargeSettings(
            grid_charge_enabled=value(self.GRID_CHARGE_ENABLED) == 1,
            grid_charge_current=value(self.GRID_CHARGE_CURRENT),
            time_of_use_enabled=value(self.TOU_DAYS) & 1 == 1,
            work_mode=self.WORK_MODES.get(mode, f"mode {mode}"),
            max_charge_current=value(self.MAX_CHARGE),
            max_discharge_current=value(self.MAX_DISCHARGE),
        )


def _register_reader(registers: dict[str, Any]) -> Any:
    def value(address: str) -> int:
        if address not in registers:
            raise GatewayError(f"Register {address} missing from the inverter's answer")
        return int(registers[address])

    return value


class DeyeCloudGateway(InverterGateway):
    """:class:`InverterGateway` backed by the DeyeCloud OpenAPI."""

    def __init__(
        self,
        client: DeyeCloudClient,
        device_sn: str = "",
        sleep: Callable[[float], None] = systime.sleep,
        order_poll_seconds: float = 3.0,
        order_attempts: int = 20,
    ) -> None:
        self._client = client
        self._device_sn = device_sn
        self._sleep = sleep
        self._poll = order_poll_seconds
        self._attempts = order_attempts
        self._tou_codec = TimeOfUseCodec()
        self._mapper = ReadingMapper()

    @property
    def device_sn(self) -> str:
        if not self._device_sn:
            self._device_sn = self._discover_inverter()
        return self._device_sn

    def read_live(self) -> Reading:
        data = self._client.post("/device/latest", {"deviceList": [self.device_sn]})
        devices = data.get("deviceDataList") or []
        if not devices:
            raise GatewayError("DeyeCloud returned no data for the inverter")
        return self._mapper.map(devices[0])

    def read_time_of_use(self) -> TimeOfUseTable:
        data = self._client.post("/config/tou", {"deviceSn": self.device_sn})
        return self._tou_codec.decode(data.get("timeUseSettingItems") or [])

    def read_battery_settings(self) -> BatterySettings:
        data = self._client.post("/config/battery", {"deviceSn": self.device_sn})
        return BatterySettings(
            max_charge_current=float(data.get("maxChargeCurrent") or 0),
            shutdown_soc=int(data.get("battShutDownCapacity") or 0),
            low_soc=int(data.get("battLowCapacity") or 0),
            capacity_ah=int(data.get("battCapacity") or 0),
        )

    def read_charge_settings(self) -> ChargeSettings:
        """Asks the inverter for its control registers (an order) and maps them."""
        data = self._client.post("/strategy/dynamicControl/read", {"deviceSn": self.device_sn})
        order = self._finished_order(str(data.get("orderId") or ""))
        registers = json.loads(order.get("analysisResult") or "{}")
        return ChargeSettingsMapper().map(registers)

    def write_time_of_use(self, table: TimeOfUseTable) -> WriteResult:
        body = {
            "deviceSn": self.device_sn,
            "timeUseSettingItems": self._tou_codec.encode(table),
            "timeoutSeconds": 30,
        }
        data = self._client.post("/order/sys/tou/update", body)
        order_id = str(data.get("orderId") or "")
        if not order_id:
            return WriteResult(True, "", "sent", str(data.get("msg") or "sent"))
        return self._wait_for_order(order_id)

    def set_grid_charge(self, enabled: bool) -> WriteResult:
        body = {
            "deviceSn": self.device_sn,
            "batteryModeType": "GRID_CHARGE",
            "action": "on" if enabled else "off",
        }
        data = self._client.post("/order/battery/modeControl", body)
        order_id = str(data.get("orderId") or "")
        if not order_id:
            raise GatewayError("DeyeCloud returned no order id")
        return self._wait_for_order(order_id)

    def _wait_for_order(self, order_id: str) -> WriteResult:
        status = str(self._poll_order(order_id).get("status"))
        accepted = status == ORDER_DONE
        message = "executed" if accepted else f"order ended with status {status}"
        return WriteResult(accepted, order_id, status, message)

    def _finished_order(self, order_id: str) -> dict[str, Any]:
        if not order_id:
            raise GatewayError("DeyeCloud returned no order id")
        order = self._poll_order(order_id)
        if str(order.get("status")) != ORDER_DONE:
            raise GatewayError(f"Read order ended with status {order.get('status')}")
        return order

    def _poll_order(self, order_id: str) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for _ in range(self._attempts):
            self._sleep(self._poll)
            data = self._client.get(f"/order/{order_id}")
            if str(data.get("status")) not in ORDER_PENDING:
                break
        return data

    def _discover_inverter(self) -> str:
        data = self._client.post("/station/listWithDevice", {"page": 1, "size": 10})
        for station in data.get("stationList") or []:
            for device in station.get("deviceListItems") or []:
                if device.get("deviceType") == "INVERTER":
                    return str(device["deviceSn"])
        raise GatewayError("No inverter found on the DeyeCloud account")
