from dataclasses import replace
from typing import Any

import pytest

from deye_inverter.domain.forecast import Forecast
from deye_inverter.domain.settings import Mode, SiteSettings
from deye_inverter.domain.time_of_use import TimeOfUseTable
from tests.conftest import Primed, World
from tests.fakes import at, flat_forecast, reading, winter_table


def set_mode(world: World, mode: Mode, **changes: Any) -> None:
    settings = world.services.settings.load()
    world.services.settings.save(replace(settings, mode=mode, **changes))


def test_skips_without_data(world: World) -> None:
    decision = world.services.planner.run("check 10:00")
    assert decision.status == "skipped"
    assert world.services.journal.recent("decision", 5)[0]["status"] == "skipped"


def test_off_mode_does_nothing(world: World, primed: Primed) -> None:
    primed()
    set_mode(world, Mode.OFF)
    assert world.services.planner.run("check").status == "off"


def test_dry_run_records_but_does_not_write(world: World, primed: Primed) -> None:
    world.gateway.table = winter_table(grid_charge=False)
    primed()
    world.gateway.live = reading(at(10), soc=40)
    world.services.collect_readings()
    decision = world.services.planner.run("check 10:00")
    assert decision.status == "dry-run"
    assert world.gateway.written == []
    assert decision.changed_slots


def test_live_writes_and_verifies(world: World, primed: Primed) -> None:
    world.gateway.table = winter_table(grid_charge=False)
    primed()
    world.gateway.live = reading(at(10), soc=40)
    world.services.collect_readings()
    set_mode(world, Mode.LIVE)
    first = world.services.planner.run("check 10:00")
    assert first.status == "executed"
    assert first.changes and ":" in first.changes[0]
    assert world.services.journal.recent("decision", 1)[0]["changes"] == first.changes
    assert len(world.gateway.written) == 1
    assert world.services.planner.run("again").status == "no-change"


def test_sunny_day_turns_grid_charge_off(world: World, primed: Primed) -> None:
    world.provider.forecast = flat_forecast(at(6), 12, 2.0)
    world.gateway.live = reading(at(10), soc=60, solar_today=8.0)
    primed()
    preview = world.services.planner.preview()
    reserve = next(r for r in preview.outcomes if r.rule == "reserve")
    assert reserve.overrides[3].grid_charge is False
    assert preview.status == "change"


def test_cloudy_day_plans_a_late_grid_start(world: World, primed: Primed) -> None:
    primed()
    world.gateway.live = reading(at(10), soc=70)
    world.services.collect_readings()
    decision = world.services.planner.run("check 10:00")
    assert decision.status == "dry-run"
    assert decision.desired is not None
    assert decision.desired.slots[3].start > decision.desired.slots[2].start
    assert decision.desired.slots[3].grid_charge is True


def test_each_run_fetches_the_forecast_again(world: World, primed: Primed) -> None:
    primed()
    before = len(world.provider.sites)
    world.services.planner.run("check 10:00")
    assert len(world.provider.sites) == before + 1


def test_forecast_failure_does_not_stop_the_planner(
    world: World, primed: Primed, monkeypatch: pytest.MonkeyPatch
) -> None:
    primed()

    def broken(_site: SiteSettings) -> Forecast:
        raise RuntimeError("down")

    monkeypatch.setattr(world.provider, "fetch", broken)
    decision = world.services.planner.run("check 10:00")
    assert decision.status != "skipped"
    assert "Forecast refresh failed" in decision.message


def test_live_matching_table_needs_no_change(world: World, primed: Primed) -> None:
    set_mode(world, Mode.LIVE)
    primed()
    world.gateway.live = reading(at(10), soc=70)
    world.services.collect_readings()
    assert world.services.planner.run("check 10:00").status == "executed"
    assert world.services.planner.run("check 10:15").status == "no-change"


def test_read_back_waits_for_the_cloud_and_mismatches_count_as_writes(
    world: World, primed: Primed
) -> None:
    primed()
    commands = world.services.time_of_use
    world.gateway.stale_reads = 2
    assert commands.send(winter_table(soc=40), "test").status == "executed"
    world.gateway.ignore_writes = True
    assert commands.send(winter_table(soc=45), "test").status == "mismatch"
    assert commands.writes_today() == 2


def lowering_write_pending(world: World, primed: Primed) -> None:
    """Live, one table already sent; the inverter then shows a higher protection than
    the rules want, so the next table only lowers it."""
    world.gateway.table = winter_table(grid_charge=False)
    primed()
    world.gateway.live = reading(at(10), soc=40)
    world.services.collect_readings()
    set_mode(world, Mode.LIVE)
    sent = world.services.planner.run("check 10:00").desired
    assert sent is not None
    world.gateway.table = TimeOfUseTable(
        tuple(slot.with_changes(soc=min(100, slot.soc + 10)) for slot in sent.slots)
    )
    world.services.refresh_inverter()


def test_lowering_waits_for_the_minimum_gap(world: World, primed: Primed) -> None:
    lowering_write_pending(world, primed)
    decision = world.services.planner.run("check 10:15")
    assert decision.status == "wait"
    assert decision.message.startswith("Next write allowed at")
    world.clock.moment = at(10, 31)
    assert world.services.planner.run("check 10:31").status == "executed"


def test_lowering_respects_the_daily_limit(world: World, primed: Primed) -> None:
    lowering_write_pending(world, primed)
    set_mode(world, Mode.LIVE, max_writes_per_day=1, min_minutes_between_writes=0)
    assert world.services.planner.run("check 10:15").status == "limit"


def test_raising_the_protection_ignores_the_gap_and_the_limit(world: World, primed: Primed) -> None:
    world.gateway.table = winter_table(grid_charge=False)
    primed()
    world.gateway.live = reading(at(10), soc=40)
    world.services.collect_readings()
    set_mode(world, Mode.LIVE)
    assert world.services.planner.run("check 10:00").status == "executed"
    world.gateway.table = winter_table(soc=20, grid_charge=False)
    world.services.refresh_inverter()
    set_mode(world, Mode.LIVE, max_writes_per_day=1, max_raising_writes_per_day=2)
    decision = world.services.planner.run("check 10:15")
    assert decision.status == "executed"
    assert "protection raised" in decision.message
    world.gateway.table = winter_table(soc=20, grid_charge=False)
    world.services.refresh_inverter()
    assert world.services.planner.run("check 10:30").status == "limit"
