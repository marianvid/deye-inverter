"""DeyeCloud station history: daily energies and 5-minute power frames."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from deye_inverter.adapters.deye_cloud import DeyeCloudClient
from deye_inverter.domain.energy import DailyEnergy, EnergyBalance
from deye_inverter.domain.readings import Reading
from deye_inverter.ports import EnergyHistorySource, GatewayError

GRANULARITY_FRAME = 1
GRANULARITY_DAY = 2
MAX_DAYS_PER_CALL = 30
SOURCE = "cloud"


class DeyeCloudHistory(EnergyHistorySource):
    def __init__(self, client: DeyeCloudClient, timezone: str, station_id: str = "") -> None:
        self._client = client
        self._zone = ZoneInfo(timezone)
        self._station_id = station_id
        self._first_day: date | None = None

    @property
    def station_id(self) -> str:
        if not self._station_id:
            self._station_id = self._discover_station()
        return self._station_id

    def first_day(self) -> date:
        if self._first_day is None:
            self._first_day = self._operating_since()
        return self._first_day

    def daily(self, start: date, end: date) -> list[DailyEnergy]:
        records: list[DailyEnergy] = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=MAX_DAYS_PER_CALL - 1))
            records.extend(self._daily_chunk(chunk_start, chunk_end))
            chunk_start = chunk_end + timedelta(days=1)
        return records

    def frames(self, day: date) -> list[Reading]:
        items = self._history(
            GRANULARITY_FRAME, day.isoformat(), (day + timedelta(days=1)).isoformat()
        )
        return [self._frame(item) for item in items if item.get("timeStamp")]

    def _daily_chunk(self, start: date, end: date) -> list[DailyEnergy]:
        items = self._history(
            GRANULARITY_DAY, start.isoformat(), (end + timedelta(days=1)).isoformat()
        )
        return [self._daily(item) for item in items if item.get("day")]

    def _history(self, granularity: int, start: str, end: str) -> list[dict[str, Any]]:
        body = {
            "stationId": self.station_id,
            "granularity": granularity,
            "startAt": start,
            "endAt": end,
        }
        return list(self._client.post("/station/history", body).get("stationDataItems") or [])

    @staticmethod
    def _daily(item: dict[str, Any]) -> DailyEnergy:
        balance = EnergyBalance(
            solar=_value(item, "generationValue"),
            consumption=_value(item, "consumptionValue"),
            bought=_value(item, "purchaseValue"),
            charged=_value(item, "chargeValue"),
            discharged=_value(item, "dischargeValue"),
        )
        return DailyEnergy(
            date(int(item["year"]), int(item["month"]), int(item["day"])), balance, SOURCE
        )

    @staticmethod
    def _frame(item: dict[str, Any]) -> Reading:
        return Reading(
            taken_at=datetime.fromtimestamp(float(item["timeStamp"]), tz=UTC),
            solar_power=_value(item, "generationPower"),
            load_power=_value(item, "consumptionPower"),
            backup_load_power=0.0,
            grid_power=_value(item, "purchasePower"),
            battery_power=_value(item, "batteryPower"),
            battery_soc=_value(item, "batterySOC"),
            battery_voltage=0.0,
            solar_today=0.0,
            load_today=0.0,
            grid_bought_today=0.0,
            battery_charged_today=0.0,
            battery_discharged_today=0.0,
            raw={"source": "cloud-frame"},
        )

    def _discover_station(self) -> str:
        data = self._client.post("/station/list", {"page": 1, "size": 10})
        stations = data.get("stationList") or []
        if not stations:
            raise GatewayError("No station on the DeyeCloud account")
        return str(stations[0]["id"])

    def _operating_since(self) -> date:
        data = self._client.post("/station/list", {"page": 1, "size": 10})
        for station in data.get("stationList") or []:
            if str(station.get("id")) == self.station_id and station.get("startOperatingTime"):
                started = datetime.fromtimestamp(
                    float(station["startOperatingTime"]), tz=self._zone
                )
                return started.date()
        raise GatewayError("DeyeCloud did not report when the station started")


def _value(item: dict[str, Any], key: str) -> float:
    value = item.get(key)
    return float(value) if value is not None else 0.0
