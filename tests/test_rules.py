from dataclasses import replace
from datetime import time

import pytest

from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.load import LoadProfile
from deye_inverter.domain.rules import (
    FloorRule,
    JustInTimeCharge,
    PlannerContext,
    next_after,
    round_down,
    running_since,
)
from deye_inverter.domain.settings import FloorSettings, SiteSettings, TuningSettings
from tests.fakes import at, flat_forecast, winter_table

# at(...) defaults to Monday 2026-10-05; the winter table starts slots at 01, 05, 09, 13, 17, 21.
TUNING = TuningSettings()


def context(
    now, soc=60.0, forecast=None, load_kw=0.6, ratio=1.0, current=None, floor=20
) -> PlannerContext:
    return PlannerContext(
        now=now,
        soc=soc,
        base_table=winter_table(),
        forecast=forecast if forecast is not None else Forecast(()),
        solar_ratio=ratio,
        load=LoadProfile.flat(load_kw),
        grid_charge_kw=5.0,
        site=SiteSettings(),
        floor_soc=floor,
        current_table=current,
    )


def charging_from(index: int, hour: int, minute: int):
    """The winter table with one slot moved and grid charge on, as the planner sends it."""
    base = winter_table()
    moved = base.slots[index].with_changes(start=time(hour, minute), grid_charge=True)
    return base.replace_slots({index: moved})


def plan(ctx, target=75, deadline=None, tuning=TUNING):
    return JustInTimeCharge("test", tuning).plan(ctx, deadline or at(16), target)


# --- just-in-time charge: 75 % by 16:00 ------------------------------------------------


def test_enough_sun_keeps_the_target_without_grid() -> None:
    outcome = plan(context(at(10), forecast=flat_forecast(at(10), 6, 2.0)))
    assert list(outcome.overrides) == [3]
    slot = outcome.overrides[3]
    assert (slot.start, slot.soc, slot.grid_charge) == (time(13, 0), 75, False)
    assert float(outcome.figures["projected_soc"]) >= 75


def test_small_deficit_moves_the_slot_start_as_late_as_possible() -> None:
    # 70 % at 10:00, no sun, 0.6 kW: 47.5 % at 16:00, 4.4 kWh short,
    # 0.88 h at 5 kW x1.2 = 1.06 h before 16:00, rounded down to 14:55.
    outcome = plan(context(at(10), soc=70))
    slot = outcome.overrides[3]
    assert (slot.start, slot.soc, slot.grid_charge) == (time(14, 55), 75, True)
    assert outcome.summary.endswith("starts at 14:55.")


def test_margin_and_step_come_from_tuning() -> None:
    tuning = replace(TUNING, charge_margin=1.0, start_step_minutes=15)
    # 0.88 h before 16:00 = 15:07, rounded down to 15:00.
    assert plan(context(at(10), soc=70), tuning=tuning).overrides[3].start == time(15, 0)


def test_late_estimate_starts_now() -> None:
    outcome = plan(context(at(13, 7), soc=21, load_kw=1.5), target=100)
    assert outcome.overrides[3].start == time(13, 5)
    assert outcome.summary.endswith("starts now.")


def test_planned_start_is_kept_within_tolerance_and_once_charging() -> None:
    kept = plan(context(at(10), soc=70, current=charging_from(3, 14, 45)))
    assert kept.overrides[3].start == time(14, 45)
    moved = plan(context(at(10), soc=70, current=charging_from(3, 14, 20)))
    assert moved.overrides[3].start == time(14, 55)
    running = plan(context(at(15), soc=68, current=charging_from(3, 14, 50)))
    assert running.overrides[3].start == time(14, 50)


def test_base_slot_that_would_charge_too_early_is_moved() -> None:
    outcome = plan(context(at(13), soc=60, current=winter_table()))
    assert outcome.overrides[3].start > time(13, 15)


def test_start_before_the_previous_slot_charges_in_both_slots() -> None:
    slow = replace(context(at(9, 2), soc=21, load_kw=1.5), grid_charge_kw=1.0)
    outcome = plan(slow, target=100)
    assert set(outcome.overrides) == {2, 3}


def test_projection_stops_at_the_floor() -> None:
    outcome = plan(context(at(10), soc=40, load_kw=3.0, floor=30))
    assert outcome.figures["projected_soc"] == 30.0


# --- floor and time helpers -----------------------------------------------------------


def test_floor_sets_every_slot() -> None:
    outcome = FloorRule(FloorSettings()).evaluate(context(at(22)))
    assert set(outcome.overrides) == set(range(6))
    assert {(s.soc, s.grid_charge) for s in outcome.overrides.values()} == {(30, False)}
    clamped = FloorRule(FloorSettings(soc=5)).evaluate(context(at(22)))
    assert {s.soc for s in clamped.overrides.values()} == {20}


def test_time_helpers() -> None:
    table = winter_table()
    assert next_after(time(16), at(16)) == at(16, day=6)
    assert running_since(table, time(16), at(16, 30)) == at(16)
    assert running_since(table, time(16), at(15)) is None
    assert running_since(table, time(21), at(0, 30, day=6)) == at(21)
    assert running_since(table, time(21), at(1, 0, day=6)) is None
    assert round_down(at(10, 7), 5) == at(10, 5)


def test_check_times_and_load_profile() -> None:
    times = TuningSettings().check_times()
    assert len(times) == 96 and times[0] == time(0) and times[-1] == time(23, 45)
    profile = LoadProfile(tuple(float(h) for h in range(24)))
    assert profile.energy_between(at(10, 30), at(12)) == pytest.approx(0.5 * 10 + 11)
    with pytest.raises(ValueError):
        LoadProfile((1.0,))


def test_protects_more_than() -> None:
    base = winter_table(grid_charge=False)
    assert not base.protects_more_than(base)
    assert winter_table(soc=60, grid_charge=False).protects_more_than(base)
    assert not winter_table(soc=50, grid_charge=False).protects_more_than(base)
    assert winter_table().protects_more_than(base)
    later = charging_from(3, 14, 0)
    earlier = charging_from(3, 13, 30)
    assert earlier.protects_more_than(later) and not later.protects_more_than(earlier)


def test_start_is_kept_when_the_next_slot_was_moved_over_the_deadline() -> None:
    # 17:00's slot moved to 15:30 now covers 16:00 too; 16:00's own slot starts at 14:45.
    base = winter_table()
    current = base.replace_slots(
        {
            3: base.slots[3].with_changes(start=time(14, 45), grid_charge=True),
            4: base.slots[4].with_changes(start=time(15, 30), grid_charge=True),
        }
    )
    outcome = plan(context(at(10), soc=70, current=current))
    assert outcome.overrides[3].start == time(14, 45)


def test_describe_changes() -> None:
    before = winter_table(grid_charge=False)
    after = before.replace_slots(
        {
            0: before.slots[0].with_changes(soc=90, grid_charge=True),
            3: before.slots[3].with_changes(start=time(14, 45)),
        }
    )
    assert after.describe_changes(before) == [
        "01:00: SOC 55% → 90%, grid charge on",
        "13:00: starts 14:45",
    ]
    assert before.describe_changes(before) == []
