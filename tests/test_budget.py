import pandas as pd
import pytest

from power_budget.budget import build_power_budget
from power_budget.modes import Mode
from power_budget.schedule import OrbitSchedule, ScheduleEntry


def test_build_power_budget_scalars(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    assert pb.orbit_average_power_w == pytest.approx(42280.0 / 5760.0)
    assert pb.peak_power_w == pytest.approx(12.0)
    assert pb.total_energy_j == pytest.approx(42280.0)
    assert pb.phase_energy["sunlight"].energy_j == pytest.approx(23700.0)
    assert pb.phase_energy["eclipse"].energy_j == pytest.approx(18580.0)


def test_build_power_budget_table_structure(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    table = pb.table
    assert isinstance(table, pd.DataFrame)
    assert set(table.columns) == {
        "power_w",
        "duty_cycle",
        "duration_s",
        "energy_j",
        "energy_wh",
        "n_spans",
    }
    # nominal mode appears twice in the schedule -> aggregated to one row
    assert "nominal" in table.index
    assert table.loc["nominal", "n_spans"] == 2
    assert table.loc["nominal", "duration_s"] == pytest.approx(3000.0 + 760.0)

    assert table.loc["payload_imaging", "n_spans"] == 1
    assert table.loc["downlink", "duration_s"] == pytest.approx(800.0)

    # duty cycles must sum to 1 (full orbit coverage)
    assert table["duty_cycle"].sum() == pytest.approx(1.0)
    # per-mode energy must sum to total schedule energy
    assert table["energy_j"].sum() == pytest.approx(42280.0)
    # table is sorted by energy_j descending
    assert list(table["energy_j"]) == sorted(table["energy_j"], reverse=True)


def test_build_power_budget_rejects_inconsistent_mode_power(orbit):
    a1 = Mode("a", 1.0)
    a2 = Mode("a", 2.0)  # same name, different power -> ambiguous
    entries = (ScheduleEntry(a1, 0.0, 100.0), ScheduleEntry(a2, 100.0, orbit.period_s))
    sched = OrbitSchedule(entries=entries, orbit_period_s=orbit.period_s)
    with pytest.raises(ValueError, match="inconsistent"):
        build_power_budget(sched, orbit)


def test_summary_contains_key_numbers(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    text = pb.summary()
    assert "Orbit-average power" in text
    assert "Peak power" in text
    assert f"{pb.peak_power_w:.2f}" in text
