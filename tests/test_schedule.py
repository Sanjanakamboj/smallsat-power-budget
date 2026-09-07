import pytest

from power_budget.modes import Mode
from power_budget.schedule import OrbitSchedule, ScheduleEntry

A = Mode("a", 2.0)
B = Mode("b", 4.0)


def test_schedule_entry_duration_and_energy():
    e = ScheduleEntry(A, 0.0, 10.0)
    assert e.duration_s == pytest.approx(10.0)
    assert e.energy_j == pytest.approx(20.0)


def test_schedule_entry_rejects_bad_bounds():
    with pytest.raises(ValueError):
        ScheduleEntry(A, -1.0, 10.0)
    with pytest.raises(ValueError):
        ScheduleEntry(A, 10.0, 10.0)
    with pytest.raises(ValueError):
        ScheduleEntry(A, 10.0, 5.0)


def test_valid_full_coverage_schedule():
    entries = (ScheduleEntry(A, 0.0, 50.0), ScheduleEntry(B, 50.0, 100.0))
    s = OrbitSchedule(entries=entries, orbit_period_s=100.0)
    assert len(s) == 2
    assert s.total_duration_s() == pytest.approx(100.0)


def test_rejects_gap():
    entries = (ScheduleEntry(A, 0.0, 40.0), ScheduleEntry(B, 50.0, 100.0))
    with pytest.raises(ValueError, match="gap"):
        OrbitSchedule(entries=entries, orbit_period_s=100.0)


def test_rejects_overlap():
    entries = (ScheduleEntry(A, 0.0, 60.0), ScheduleEntry(B, 50.0, 100.0))
    with pytest.raises(ValueError, match="overlap"):
        OrbitSchedule(entries=entries, orbit_period_s=100.0)


def test_rejects_non_zero_start():
    entries = (ScheduleEntry(A, 5.0, 100.0),)
    with pytest.raises(ValueError, match="start at t=0"):
        OrbitSchedule(entries=entries, orbit_period_s=100.0)


def test_rejects_incomplete_coverage():
    entries = (ScheduleEntry(A, 0.0, 90.0),)
    with pytest.raises(ValueError, match="full orbit period"):
        OrbitSchedule(entries=entries, orbit_period_s=100.0)


def test_rejects_empty_entries():
    with pytest.raises(ValueError):
        OrbitSchedule(entries=(), orbit_period_s=100.0)


def test_rejects_nonpositive_period():
    entries = (ScheduleEntry(A, 0.0, 100.0),)
    with pytest.raises(ValueError):
        OrbitSchedule(entries=entries, orbit_period_s=0.0)


def test_mode_at_interior_points():
    entries = (ScheduleEntry(A, 0.0, 50.0), ScheduleEntry(B, 50.0, 100.0))
    s = OrbitSchedule(entries=entries, orbit_period_s=100.0)
    assert s.mode_at(0.0) is A
    assert s.mode_at(49.9) is A
    assert s.mode_at(50.0) is B
    assert s.mode_at(99.9) is B


def test_mode_at_wraps_at_period_boundary():
    entries = (ScheduleEntry(A, 0.0, 50.0), ScheduleEntry(B, 50.0, 100.0))
    s = OrbitSchedule(entries=entries, orbit_period_s=100.0)
    # exactly at period should wrap to t=0 -> mode A
    assert s.mode_at(100.0) is A
    # one full period plus 60 s should equal t=60 -> mode B
    assert s.mode_at(160.0) is B
