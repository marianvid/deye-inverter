from datetime import time

import pytest

from deye_inverter.domain.time_of_use import (
    TimeOfUseError,
    TimeOfUseSlot,
    TimeOfUseTable,
    table_from_dicts,
    table_to_dicts,
)
from tests.fakes import winter_table


def test_index_at_finds_active_slot_including_wrap() -> None:
    table = winter_table()
    assert table.index_at(time(16, 0)) == 3
    assert table.index_at(time(0, 30)) == 5
    assert table.index_at(time(1, 0)) == 0


def test_overlapping_window_and_midnight_wrap() -> None:
    table = winter_table()
    assert table.indexes_overlapping(16 * 60, 16 * 60 + 1) == [3]
    assert table.indexes_overlapping(11 * 60, 16 * 60) == [2, 3]
    assert table.indexes_overlapping(23 * 60, 2 * 60) == [0, 5]


def test_table_validation() -> None:
    slot = winter_table().slots[0]
    with pytest.raises(TimeOfUseError):
        TimeOfUseTable((slot,) * 6)
    with pytest.raises(TimeOfUseError):
        TimeOfUseTable(winter_table().slots[:5])
    with pytest.raises(TimeOfUseError):
        TimeOfUseSlot(time(1, 0), 101, 0, 0, False, False)
    with pytest.raises(TimeOfUseError):
        TimeOfUseSlot(time(1, 0), 50, -1, 0, False, False)


def test_round_trip_and_differences() -> None:
    table = winter_table()
    assert table_from_dicts(table_to_dicts(table)) == table
    changed = table.replace_slots({2: table.slots[2].with_changes(soc=30)})
    assert changed.differences(table) == [2]
    assert table.end_minute(5) == 25 * 60
