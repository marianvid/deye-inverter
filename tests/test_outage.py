from dataclasses import replace
from datetime import time

from deye_inverter.application.planner_service import merge_slot
from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.load import LoadProfile
from deye_inverter.domain.outage import OutageLoad, OutageSimulation
from deye_inverter.domain.reserve import ReserveRule
from deye_inverter.domain.rules import PlannerContext
from deye_inverter.domain.settings import ReserveSettings, SiteSettings, TuningSettings
from tests.fakes import at, flat_forecast, winter_table

BASE = LoadProfile.flat(0.25)  # night load 0.25 kW -> 0.3125 kW with the 1.25 margin
NEXT_MORNING_SUN = flat_forecast(at(9, day=6), 8, 2.0)


def simulation(forecast, **changes) -> OutageSimulation:
    settings = ReserveSettings(**changes)
    return OutageSimulation(settings, OutageLoad(settings, BASE), forecast, 16.0, 20)


def test_outage_load_by_time_of_day() -> None:
    load = OutageLoad(ReserveSettings(), LoadProfile.flat(0.8))
    assert load.kw(at(17)) == 0.9
    assert load.kw(at(21)) == 0.4
    assert load.kw(at(7)) == 1.0
    assert load.kw(at(3)) == 0.5  # 0.8 x 1.25 capped at 0.5
    assert OutageLoad(ReserveSettings(), BASE).kw(at(3)) == 0.3125


def test_winter_evening_without_sun() -> None:
    # 16-20: 3.6 kWh, 20-22: 0.8, 22-06: 2.5, 06-09: 3.0 = 9.9 kWh = 61.9 % + 20 %.
    assert simulation(NEXT_MORNING_SUN).required_at(at(16)) == 82


def test_sun_after_four_lowers_the_reserve() -> None:
    sunny = Forecast(flat_forecast(at(16), 4, 2.0).hours + NEXT_MORNING_SUN.hours)
    assert simulation(sunny).required_at(at(16)) < 82 - 15


def test_early_morning_sun_shortens_the_morning() -> None:
    early = Forecast(flat_forecast(at(7, day=6), 10, 2.0).hours)
    assert simulation(early).required_at(at(5, day=6)) < simulation(NEXT_MORNING_SUN).required_at(
        at(5, day=6)
    )


def test_a_sunny_break_before_night_does_not_end_the_outage() -> None:
    cloudy_then_break = Forecast(
        flat_forecast(at(16), 1, 0.1).hours
        + flat_forecast(at(17), 1, 2.0).hours
        + NEXT_MORNING_SUN.hours
    )
    assert simulation(cloudy_then_break).required_at(at(16)) > 60


def test_cap_and_generator() -> None:
    assert simulation(NEXT_MORNING_SUN, max_soc=60).required_at(at(16)) == 60
    assert simulation(NEXT_MORNING_SUN, generator_available=True).required_at(at(16)) == 26
    assert simulation(Forecast(())).required_at(at(16)) == 90


def context(now, soc=60.0, current=None) -> PlannerContext:
    return PlannerContext(
        now=now,
        soc=soc,
        base_table=winter_table(),
        forecast=NEXT_MORNING_SUN,
        solar_ratio=1.0,
        load=BASE,
        grid_charge_kw=5.0,
        site=SiteSettings(),
        floor_soc=30,
        current_table=current,
    )


def rule(**changes) -> ReserveRule:
    return ReserveRule(ReserveSettings(**changes), TuningSettings())


def test_protected_moments() -> None:
    assert rule().moments(winter_table()) == [time(16), time(17), time(21), time(1), time(5)]


def test_rule_sets_every_protected_slot() -> None:
    outcome = rule().evaluate(context(at(10)))
    assert set(outcome.overrides) == {0, 1, 3, 4, 5}
    assert outcome.figures["reserve 16:00"] == 82
    slot = outcome.overrides[3]
    assert slot.soc == 82 and slot.grid_charge is True and slot.start > time(13, 0)
    assert outcome.summary.startswith("Outage reserve: 16:00 82%")
    assert "Short:" in outcome.summary


def test_no_grid_when_the_battery_is_enough() -> None:
    outcome = rule().evaluate(context(at(10), soc=100))
    assert not any(slot.grid_charge for slot in outcome.overrides.values())
    assert outcome.summary.endswith("Reached without the grid.")


def test_running_slot_holds_its_moments_reserve() -> None:
    late = rule().evaluate(context(at(23, 30), soc=80))
    slot = late.overrides[5]  # the 21:00 slot is running
    assert slot.start == time(21, 0) and slot.grid_charge is False
    assert slot.soc == late.figures["reserve 21:00"]
    short = rule().evaluate(context(at(23, 30), soc=25))
    assert short.overrides[5].grid_charge is True
    assert "below the 21:00 reserve now" in short.summary
    morning = rule().evaluate(context(at(7, 30, day=6), soc=80))
    assert morning.overrides[1].start == time(5, 0)  # held until 09:00


def test_days_and_disable() -> None:
    assert rule(weekdays=(5, 6)).evaluate(context(at(10))).summary.startswith("Not active")
    assert not rule(enabled=False).evaluate(context(at(10))).overrides


def test_reserve_on_the_inverter_is_kept_within_the_tolerance() -> None:
    fresh = rule().evaluate(context(at(10), soc=100)).overrides[4]
    near = winter_table().replace_slots({4: fresh.with_changes(soc=fresh.soc + 2)})
    far = winter_table().replace_slots({4: fresh.with_changes(soc=fresh.soc + 5)})
    assert rule().evaluate(context(at(10), 100, near)).overrides[4].soc == fresh.soc + 2
    assert rule().evaluate(context(at(10), 100, far)).overrides[4].soc == fresh.soc


def test_merge_keeps_the_start_when_a_move_would_cross_a_neighbour() -> None:
    table = winter_table()
    crossing = table.slots[4].with_changes(start=time(12, 0), soc=90)
    merged = merge_slot(table, 4, crossing)
    assert merged.slots[4].start == time(17, 0) and merged.slots[4].soc == 90
    assert replace(crossing, start=time(17, 0)) == merged.slots[4]
