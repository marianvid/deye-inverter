from dataclasses import replace

from deye_inverter.domain.settings import Mode
from tests.fakes import at, flat_forecast, reading, winter_table


def set_mode(world, mode: Mode, **changes) -> None:
    settings = world.services.settings.load()
    world.services.settings.save(replace(settings, mode=mode, **changes))


def test_skips_without_data(world) -> None:
    decision = world.services.planner.run("check 10:00")
    assert decision.status == "skipped"
    assert world.services.journal.recent("decision", 5)[0]["status"] == "skipped"


def test_off_mode_does_nothing(world, primed) -> None:
    primed()
    set_mode(world, Mode.OFF)
    assert world.services.planner.run("check").status == "off"


def test_dry_run_records_but_does_not_write(world, primed) -> None:
    world.gateway.table = winter_table(grid_charge=False)
    primed()
    world.gateway.live = reading(at(10), soc=40)
    world.services.collect_readings()
    decision = world.services.planner.run("check 10:00")
    assert decision.status == "dry-run"
    assert world.gateway.written == []
    assert decision.changed_slots


def test_live_writes_verifies_and_respects_limit(world, primed) -> None:
    world.gateway.table = winter_table(grid_charge=False)
    primed()
    world.gateway.live = reading(at(10), soc=40)
    world.services.collect_readings()
    set_mode(world, Mode.LIVE, max_writes_per_day=1)
    first = world.services.planner.run("check 10:00")
    assert first.status == "executed"
    assert len(world.gateway.written) == 1
    assert world.services.planner.run("again").status == "no-change"
    world.gateway.table = world.services.state.base_table()
    world.services.refresh_inverter()
    assert world.services.planner.run("third").status == "limit"


def test_sunny_day_turns_grid_charge_off(world, primed) -> None:
    world.provider.forecast = flat_forecast(at(6), 12, 2.0)
    world.gateway.live = reading(at(10), soc=60, solar_today=8.0)
    primed()
    preview = world.services.planner.preview()
    reserve = next(r for r in preview.outcomes if r.rule == "reserve")
    assert reserve.overrides[3].grid_charge is False
    assert preview.status == "change"


def test_cloudy_day_plans_a_late_grid_start(world, primed) -> None:
    primed()
    world.gateway.live = reading(at(10), soc=70)
    world.services.collect_readings()
    decision = world.services.planner.run("check 10:00")
    assert decision.status == "dry-run"
    assert decision.desired is not None
    assert decision.desired.slots[3].start > decision.desired.slots[2].start
    assert decision.desired.slots[3].grid_charge is True


def test_each_run_fetches_the_forecast_again(world, primed) -> None:
    primed()
    before = len(world.provider.sites)
    world.services.planner.run("check 10:00")
    assert len(world.provider.sites) == before + 1


def test_forecast_failure_does_not_stop_the_planner(world, primed) -> None:
    primed()

    def broken(_site):
        raise RuntimeError("down")

    world.provider.fetch = broken
    decision = world.services.planner.run("check 10:00")
    assert decision.status != "skipped"
    assert "Forecast refresh failed" in decision.message


def test_live_matching_table_needs_no_change(world, primed) -> None:
    set_mode(world, Mode.LIVE)
    primed()
    world.gateway.live = reading(at(10), soc=70)
    world.services.collect_readings()
    assert world.services.planner.run("check 10:00").status == "executed"
    assert world.services.planner.run("check 10:15").status == "no-change"


def test_read_back_waits_for_the_cloud_and_mismatches_count_as_writes(world, primed) -> None:
    primed()
    commands = world.services.time_of_use
    world.gateway.stale_reads = 2
    assert commands.send(winter_table(soc=40), "test").status == "executed"
    world.gateway.ignore_writes = True
    assert commands.send(winter_table(soc=45), "test").status == "mismatch"
    assert commands.writes_today() == 2
