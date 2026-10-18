from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from deye_inverter.adapters.sqlite_store import Database
from deye_inverter.container import Outside, Services, Storage, build_services
from tests.fakes import (
    FakeForecastProvider,
    FakeGateway,
    FakeHistory,
    FixedClock,
    at,
    flat_forecast,
)


@dataclass
class World:
    services: Services
    gateway: FakeGateway
    clock: FixedClock
    provider: FakeForecastProvider
    history: FakeHistory


# What the `primed` fixture returns: call it to collect data, get the world back.
Primed = Callable[[], World]


@pytest.fixture
def world() -> World:
    gateway = FakeGateway()
    clock = FixedClock(at(10))
    provider = FakeForecastProvider(flat_forecast(at(0), 48, 0.0))
    history = FakeHistory()
    outside = Outside(
        gateway, provider, history, clock, "Europe/Bucharest", sleep=lambda _seconds: None
    )
    services = build_services(Database(":memory:"), outside)
    return World(services, gateway, clock, provider, history)


@dataclass
class Parts:
    """The repositories and fakes, for testing one application class without the container."""

    db: Storage
    gateway: FakeGateway
    clock: FixedClock
    provider: FakeForecastProvider
    history: FakeHistory


@pytest.fixture
def parts() -> Parts:
    gateway = FakeGateway()
    clock = FixedClock(at(10))
    provider = FakeForecastProvider(flat_forecast(at(0), 48, 0.0))
    history = FakeHistory()
    outside = Outside(gateway, provider, history, clock, "Europe/Bucharest")
    return Parts(Storage.open(Database(":memory:"), outside), gateway, clock, provider, history)


@pytest.fixture
def primed(world: World) -> Primed:
    """A world in which readings, inverter settings and a forecast were collected."""

    def prime() -> World:
        world.services.collect_readings()
        world.services.refresh_inverter()
        world.services.refresh_forecast()
        return world

    return prime
