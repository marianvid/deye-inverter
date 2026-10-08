from datetime import date

import pytest

from deye_inverter.application.statistics import Period, SpanCalculator, averaged
from tests.fakes import at, reading


@pytest.fixture
def filled(world, primed):
    primed()
    world.services.sync_daily()
    world.services.record_today()
    world.services.backfill()
    return world


def test_spans_and_navigation() -> None:
    calc = SpanCalculator(today=date(2026, 10, 5), first_day=date(2026, 6, 12))
    week = calc.span(Period.WEEK, date(2026, 10, 1))
    assert (week.start, week.end) == (date(2026, 9, 28), date(2026, 10, 4))
    assert week.next == date(2026, 10, 5) and week.previous == date(2026, 9, 21)
    month = calc.span(Period.MONTH, date(2026, 2, 10))
    assert (month.start, month.end) == (date(2026, 2, 1), date(2026, 2, 28))
    year = calc.span(Period.YEAR, date(2026, 7, 1))
    assert year.previous is None and year.next is None and year.label == "2026"
    day = calc.span(Period.DAY, date(2026, 10, 5))
    assert day.next is None and day.previous == date(2026, 10, 4)
    assert calc.span(Period.LIFETIME, date(2026, 10, 5)).start == date(2026, 6, 12)


def test_day_summary_has_curve_and_totals(filled) -> None:
    stats = filled.services.statistics.summary(Period.DAY, date(2026, 10, 4))
    assert stats["totals"] == {
        "solar": 10,
        "consumption": 8,
        "from_solar": 6,
        "from_grid": 2,
        "charged": 3,
        "discharged": 3,
        "self_sufficiency": 75.0,
    }
    assert len(stats["curve"]["times"]) == 12 and stats["buckets"] == []


def test_week_month_year_lifetime(filled) -> None:
    stats = filled.services.statistics
    week = stats.summary(Period.WEEK, date(2026, 10, 5))
    assert week["days_with_data"] == 1 and week["curve"]["times"]
    month = stats.summary(Period.MONTH, date(2026, 10, 5))
    assert month["totals"]["consumption"] == 8 * 4 + 5
    assert len(month["buckets"]) == 5 and month["soc_by_day"][0]["min"] == 50
    year = stats.summary(Period.YEAR)
    assert year["buckets"][0]["label"] == "2026-10"
    lifetime = stats.summary(Period.LIFETIME)
    assert lifetime["buckets"][0]["label"] == "2026"
    assert lifetime["inverter_counters"] is not None


def test_future_anchor_is_clamped(filled) -> None:
    assert filled.services.statistics.summary(Period.DAY, date(2030, 1, 1))["start"] == "2026-10-05"


def test_averaged_buckets() -> None:
    points = averaged(
        [reading(at(10, 0), soc=40), reading(at(10, 5), soc=60), reading(at(10, 20), soc=80)], 15
    )
    assert [p.battery_soc for p in points] == [50, 80]
