"""JSON API used by the pages' JavaScript. One controller class per area."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from deye_inverter.application.manual_charge import ManualChargeLockedError
from deye_inverter.application.profiles import ProfileError, ProfilesLockedError
from deye_inverter.application.statistics import Period
from deye_inverter.container import Services
from deye_inverter.domain.manual import ManualChargeError
from deye_inverter.domain.settings import Mode
from deye_inverter.domain.time_of_use import TimeOfUseError, TimeOfUseTable, table_from_dicts
from deye_inverter.ports import GatewayError


class MonitoringApi:
    def __init__(self, services: Services) -> None:
        self._views = services.views
        self._statistics = services.statistics
        self.router = APIRouter(prefix="/api")
        self.router.add_api_route("/now", self.now, methods=["GET"])
        self.router.add_api_route("/history/day", self.day, methods=["GET"])
        self.router.add_api_route("/statistics", self.statistics, methods=["GET"])
        self.router.add_api_route("/forecast", self.forecast, methods=["GET"])

    def now(self) -> dict[str, Any]:
        return self._views.now()

    def day(self, day: date = Query(...)) -> dict[str, Any]:  # noqa: B008
        return self._views.day_series(day)

    def statistics(self, period: str = "day", day: date | None = None) -> dict[str, Any]:
        try:
            chosen = Period(period)
        except ValueError as error:
            raise HTTPException(400, f"Unknown period {period}") from error
        return self._statistics.summary(chosen, day)

    def forecast(self) -> dict[str, Any]:
        return self._views.forecast()


class PlanApi:
    def __init__(self, services: Services) -> None:
        self._services = services
        self.router = APIRouter(prefix="/api/plan")
        self.router.add_api_route("", self.overview, methods=["GET"])
        self.router.add_api_route("/run", self.run_now, methods=["POST"])
        self.router.add_api_route("/mode", self.set_mode, methods=["POST"])

    def overview(self) -> dict[str, Any]:
        settings = self._services.settings.load()
        scheduler = self._services.scheduler
        return {
            "mode": settings.mode.value,
            "writes_today": self._services.time_of_use.writes_today(),
            "max_writes_per_day": settings.max_writes_per_day,
            "preview": self._services.planner.preview().as_dict(),
            "decisions": self._services.journal.recent("decision", 20),
            "next_runs": scheduler.next_runs() if scheduler else [],
        }

    def run_now(self) -> dict[str, Any]:
        return self._services.planner.run("manual").as_dict()

    def set_mode(self, mode: str = Body(..., embed=True)) -> dict[str, str]:
        try:
            new_mode = Mode(mode)
        except ValueError as error:
            raise HTTPException(400, f"Unknown mode {mode}") from error
        settings = self._services.settings.load()
        self._services.settings.save(replace(settings, mode=new_mode))
        if new_mode is not Mode.LIVE:
            self._services.manual.cancel("automation left Live", run_planner=False)
        return {"mode": new_mode.value}


class TimeOfUseApi:
    def __init__(self, services: Services) -> None:
        self._services = services
        self.router = APIRouter(prefix="/api/time-of-use")
        self.router.add_api_route("", self.show, methods=["GET"])
        self.router.add_api_route("/refresh", self.refresh, methods=["POST"])
        self.router.add_api_route("/base", self.save_base, methods=["POST"])
        self.router.add_api_route("/send", self.send, methods=["POST"])

    def show(self) -> dict[str, Any]:
        return self._services.views.time_of_use()

    def refresh(self) -> dict[str, Any]:
        try:
            self._services.refresh_inverter()
        except GatewayError as error:
            raise HTTPException(502, str(error)) from error
        return self.show()

    def save_base(self, slots: list[dict[str, Any]] = Body(..., embed=True)) -> dict[str, Any]:  # noqa: B008
        table = self.table(slots)
        self._services.state.save_base_table(table, self._services.clock.now())
        return self.show()

    def send(self, slots: list[dict[str, Any]] = Body(..., embed=True)) -> dict[str, Any]:  # noqa: B008
        outcome = self._services.time_of_use.send(self.table(slots), "manual")
        return {**outcome.as_dict(), **self.show()}

    @staticmethod
    def table(slots: list[dict[str, Any]]) -> TimeOfUseTable:
        try:
            return table_from_dicts(slots)
        except (TimeOfUseError, KeyError, ValueError) as error:
            raise HTTPException(400, f"Invalid table: {error}") from error


class ChargeSettingsApi:
    def __init__(self, services: Services) -> None:
        self._services = services
        self.router = APIRouter(prefix="/api/charge-settings")
        self.router.add_api_route("/grid-charge", self.set_grid_charge, methods=["POST"])

    def set_grid_charge(self, enabled: bool = Body(..., embed=True)) -> dict[str, Any]:
        outcome = self._services.charging.set_grid_charge(enabled)
        return {**outcome.as_dict(), **self._services.views.time_of_use()}


class ManualChargeApi:
    def __init__(self, services: Services) -> None:
        self._services = services
        self.router = APIRouter(prefix="/api/manual-charge")
        self.router.add_api_route("", self.show, methods=["GET"])
        self.router.add_api_route("", self.start, methods=["POST"])
        self.router.add_api_route("", self.cancel, methods=["DELETE"])

    def show(self) -> dict[str, Any]:
        return self._services.manual.status()

    def start(
        self,
        target_soc: int = Body(...),
        ready_time: str | None = Body(None),
        hold_until: str | None = Body(None),
    ) -> dict[str, Any]:
        try:
            result = self._services.manual.start(
                target_soc, _clock_time(ready_time), _clock_time(hold_until)
            )
        except ManualChargeLockedError as error:
            raise HTTPException(409, str(error)) from error
        except (ManualChargeError, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        return {**result, **self._services.manual.status()}

    def cancel(self) -> dict[str, Any]:
        self._services.manual.cancel()
        return self._services.manual.status()


def _clock_time(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


class ProfilesApi:
    def __init__(self, services: Services) -> None:
        self._services = services
        self.router = APIRouter(prefix="/api/time-of-use/profiles")
        self.router.add_api_route("", self.show, methods=["GET"])
        self.router.add_api_route("", self.save, methods=["POST"])
        self.router.add_api_route("/{name}", self.delete, methods=["DELETE"])
        self.router.add_api_route("/{name}/apply", self.apply, methods=["POST"])

    def show(self) -> dict[str, Any]:
        return {
            "mode": self._services.settings.load().mode.value,
            "profiles": [p.as_dict() for p in self._services.profiles.all()],
        }

    def save(
        self,
        name: str = Body(...),
        slots: list[dict[str, Any]] = Body(...),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            self._services.profiles.save(name, TimeOfUseApi.table(slots))
        except ProfileError as error:
            raise HTTPException(400, str(error)) from error
        return self.show()

    def delete(self, name: str) -> dict[str, Any]:
        self._services.profiles.delete(name)
        return self.show()

    def apply(self, name: str) -> dict[str, Any]:
        try:
            outcome = self._services.profiles.apply(name)
        except ProfilesLockedError as error:
            raise HTTPException(409, str(error)) from error
        except ProfileError as error:
            raise HTTPException(404, str(error)) from error
        return {**outcome.as_dict(), **self._services.views.time_of_use()}


class SettingsApi:
    def __init__(self, services: Services) -> None:
        self._services = services
        self._codec = services.settings.codec
        self.router = APIRouter(prefix="/api/settings")
        self.router.add_api_route("", self.show, methods=["GET"])
        self.router.add_api_route("", self.save, methods=["POST"])

    def show(self) -> dict[str, Any]:
        return self._codec.to_dict(self._services.settings.load())

    def save(self, data: dict[str, Any] = Body(...)) -> dict[str, Any]:  # noqa: B008
        try:
            settings = self._codec.from_dict(data)
        except (ValueError, TypeError) as error:
            raise HTTPException(400, f"Invalid settings: {error}") from error
        self._services.settings.save(settings)
        if self._services.scheduler is not None:
            self._services.scheduler.schedule_planner(settings, self._services.planner.run)
        return self.show()


class LogApi:
    def __init__(self, services: Services) -> None:
        self._journal = services.journal
        self.router = APIRouter(prefix="/api/log")
        self.router.add_api_route("", self.entries, methods=["GET"])

    def entries(
        self, kind: str | None = None, limit: int = Query(100, ge=1, le=1000)
    ) -> list[dict[str, Any]]:
        return self._journal.recent(kind, limit)
