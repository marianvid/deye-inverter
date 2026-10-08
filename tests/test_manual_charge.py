from dataclasses import replace
from datetime import time, timedelta

import pytest

from deye_inverter.application.manual_charge import ManualChargeLockedError
from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.load import LoadProfile
from deye_inverter.domain.manual import ManualCharge, ManualChargeError, ManualChargeRule
from deye_inverter.domain.rules import PlannerContext
from deye_inverter.domain.settings import Mode, SiteSettings, TuningSettings
from tests.fakes import at, reading, winter_table


def context(now, soc=60.0) -> PlannerContext:
    return PlannerContext(
        now=now,
        soc=soc,
        base_table=winter_table(),
        forecast=Forecast(()),
        solar_ratio=1.0,
        load=LoadProfile.flat(0.6),
        grid_charge_kw=5.0,
        site=SiteSettings(),
        floor_soc=30,
    )


def live(world) -> None:
    settings = world.services.settings.load()
    world.services.settings.save(replace(settings, mode=Mode.LIVE))


# --- domain ----------------------------------------------------------------------------


def test_manual_charge_validation_and_round_trip() -> None:
    with pytest.raises(ManualChargeError):
        ManualCharge(0, at(10))
    with pytest.raises(ManualChargeError):
        ManualCharge(80, at(10), ready_at=at(9))
    with pytest.raises(ManualChargeError):
        ManualCharge(80, at(10), ready_at=at(12), hold_until=at(11))
    with pytest.raises(ManualChargeError):
        ManualCharge(80, at(10), hold_until=at(10, day=8))
    charge = ManualCharge(80, at(10), at(12), at(14), True)
    assert ManualCharge.from_dict(charge.as_dict()) == charge
    with pytest.raises(ManualChargeError):
        ManualCharge.from_dict({"target_soc": 80})


def test_finished_now_and_ready_by() -> None:
    now_only = ManualCharge(80, at(10))
    assert not now_only.finished(at(11), 79) and now_only.finished(at(11), 80)
    held = ManualCharge(80, at(10), hold_until=at(15))
    assert not held.finished(at(11), 90) and held.finished(at(15), 90)
    ready = ManualCharge(80, at(10), ready_at=at(14))
    assert ready.release_at == at(14)
    assert not ready.finished(at(13), 90) and ready.finished(at(14), 10)
    assert now_only.finished(at(10) + timedelta(days=2), 0)


def test_rule_charges_now_in_the_active_slot() -> None:
    outcome = ManualChargeRule(ManualCharge(90, at(10)), TuningSettings()).evaluate(
        context(at(10, 5))
    )
    assert list(outcome.overrides) == [2]
    slot = outcome.overrides[2]
    assert (slot.start, slot.soc, slot.grid_charge) == (time(9, 0), 90, True)


def test_rule_holds_across_slots_until_the_end() -> None:
    charge = ManualCharge(70, at(10), hold_until=at(18))
    outcome = ManualChargeRule(charge, TuningSettings()).evaluate(context(at(10, 5)))
    assert set(outcome.overrides) == {2, 3, 4}
    assert "held until" in outcome.summary


def test_rule_ready_by_starts_as_late_as_possible_and_holds() -> None:
    # 60 % at 10:00, 6 h at 0.6 kW = 22.5 %: 37.5 % at 16:00, 80 % needed: 6.8 kWh short,
    # 1.36 h at 5 kW x1.2 = 1.63 h: 14:22, rounded down to 14:20.
    charge = ManualCharge(80, at(10), ready_at=at(16), hold_until=at(18))
    outcome = ManualChargeRule(charge, TuningSettings()).evaluate(context(at(10)))
    assert outcome.overrides[3].start == time(14, 20)
    assert outcome.overrides[3].grid_charge is True
    assert outcome.overrides[4].soc == 80
    assert outcome.summary.startswith("Manual: 80% by")


def test_rule_without_charge_does_nothing() -> None:
    assert not ManualChargeRule(None, TuningSettings()).evaluate(context(at(10))).overrides


# --- service ---------------------------------------------------------------------------


def test_manual_charge_only_in_live(world, primed) -> None:
    primed()
    with pytest.raises(ManualChargeLockedError):
        world.services.manual.start(80, None, None)


def test_start_now_writes_and_finishes_when_reached(world, primed) -> None:
    primed()
    live(world)
    result = world.services.manual.start(90, None, None)
    assert result["decision"]["status"] == "executed"
    active = world.gateway.table.slots[2]
    assert (active.soc, active.grid_charge) == (90, True)
    world.gateway.live = reading(at(10, 30), soc=91)
    world.services.collect_readings()
    world.services.manual.tick()
    assert world.services.manual.current() is None
    assert world.gateway.table.slots[2].soc == 30


def test_already_reached_target_is_refused(world, primed) -> None:
    primed()
    live(world)
    with pytest.raises(ManualChargeError):
        world.services.manual.start(50, None, None)


def test_grid_switch_is_turned_on_and_restored(world, primed) -> None:
    world.gateway.grid_charge = False
    primed()
    live(world)
    world.services.manual.start(90, None, None)
    assert world.gateway.grid_charge is True
    assert world.services.manual.current().restore_grid_switch_off
    world.services.manual.cancel()
    assert world.gateway.grid_charge is False
    assert world.services.manual.current() is None


def test_grid_switch_failure_stops_the_start(world, primed) -> None:
    world.gateway.grid_charge = False
    primed()
    live(world)
    world.gateway.accept = False
    with pytest.raises(ManualChargeError):
        world.services.manual.start(90, None, None)
    assert world.services.manual.current() is None


def test_ready_by_and_hold_times_resolve_to_the_next_occurrence(world, primed) -> None:
    primed()
    live(world)
    world.services.manual.start(80, time(16, 0), time(16, 0))
    charge = world.services.manual.current()
    assert charge.ready_at == at(16) and charge.hold_until == at(16)
    world.services.manual.cancel()
    world.services.manual.start(80, time(9, 0), time(8, 0))
    charge = world.services.manual.current()
    assert charge.ready_at == at(9, day=6) and charge.hold_until == at(8, day=7)


def test_tick_follows_and_ends(world, primed) -> None:
    primed()
    live(world)
    world.services.manual.tick()  # nothing active: no error
    world.services.manual.start(80, time(16, 0), None)
    world.services.manual.tick()
    assert world.services.manual.current() is not None
    world.clock.moment = at(16)
    world.services.manual.tick()
    assert world.services.manual.current() is None


def test_leaving_live_cancels(world, primed) -> None:
    primed()
    live(world)
    world.services.manual.start(90, None, None)
    settings = world.services.settings.load()
    world.services.settings.save(replace(settings, mode=Mode.DRY_RUN))
    world.services.manual.tick()
    assert world.services.manual.current() is None


def test_manual_writes_ignore_the_daily_limit(world, primed) -> None:
    primed()
    settings = world.services.settings.load()
    world.services.settings.save(replace(settings, mode=Mode.LIVE, max_writes_per_day=0))
    result = world.services.manual.start(90, None, None)
    assert result["decision"]["status"] == "executed"


def test_status_shows_battery_and_switch(world, primed) -> None:
    primed()
    status = world.services.manual.status()
    assert status["battery"]["soc"] == 60
    assert status["grid_charge_enabled"] is True
    assert status["charge"] is None and status["mode"] == "dry-run"
