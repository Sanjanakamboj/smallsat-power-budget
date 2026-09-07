import numpy as np
import pytest

from power_budget.energy import (
    energy_by_phase,
    orbit_average_power_w,
    peak_power_w,
    power_profile,
    total_energy_j,
)
from power_budget.modes import Mode
from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule, ScheduleEntry


def test_peak_power(simple_schedule):
    assert peak_power_w(simple_schedule) == pytest.approx(12.0)


def test_total_energy_and_average_power(simple_schedule):
    total_j = total_energy_j(simple_schedule)
    assert total_j == pytest.approx(42280.0)
    avg_w = orbit_average_power_w(simple_schedule)
    assert avg_w == pytest.approx(42280.0 / 5760.0)
    # average power must also equal total_energy / period computed independently
    assert avg_w == pytest.approx(total_j / simple_schedule.orbit_period_s)


def test_energy_by_phase_straddling_mode(simple_schedule, orbit):
    result = energy_by_phase(simple_schedule, orbit)
    sun, ecl = result["sunlight"], result["eclipse"]

    assert sun.duration_s == pytest.approx(3600.0)
    assert ecl.duration_s == pytest.approx(2160.0)
    # durations must reconstruct the full orbit period exactly
    assert sun.duration_s + ecl.duration_s == pytest.approx(orbit.period_s)

    assert sun.energy_j == pytest.approx(23700.0)
    assert ecl.energy_j == pytest.approx(18580.0)
    # energies must reconstruct total schedule energy exactly
    assert sun.energy_j + ecl.energy_j == pytest.approx(
        total_energy_j(simple_schedule)
    )

    assert sun.average_power_w == pytest.approx(23700.0 / 3600.0)
    assert ecl.average_power_w == pytest.approx(18580.0 / 2160.0)
    assert sun.energy_wh == pytest.approx(23700.0 / 3600.0 / 1.0)  # J -> Wh /3600


def test_energy_by_phase_rejects_mismatched_period(simple_schedule):
    bad_orbit = OrbitGeometry(period_s=1234.0, eclipse_fraction=0.3)
    with pytest.raises(ValueError):
        energy_by_phase(simple_schedule, bad_orbit)


def test_energy_by_phase_fully_sunlit_orbit():
    m = Mode("nominal", 5.0)
    entries = (ScheduleEntry(m, 0.0, 1000.0),)
    sched = OrbitSchedule(entries=entries, orbit_period_s=1000.0)
    orbit = OrbitGeometry(period_s=1000.0, eclipse_fraction=0.0)
    result = energy_by_phase(sched, orbit)
    assert result["eclipse"].duration_s == pytest.approx(0.0)
    assert result["eclipse"].energy_j == pytest.approx(0.0)
    assert result["eclipse"].average_power_w == 0.0
    assert result["sunlight"].energy_j == pytest.approx(5000.0)


def test_power_profile_shape_and_endpoints(simple_schedule):
    t_s, p_w = power_profile(simple_schedule, dt_s=10.0)
    assert t_s[0] == pytest.approx(0.0)
    assert t_s[-1] == pytest.approx(simple_schedule.orbit_period_s)
    assert len(t_s) == len(p_w)
    assert np.all(np.diff(t_s) > 0)
    # first sample must equal the power of the mode starting at t=0
    assert p_w[0] == pytest.approx(5.5)


def test_power_profile_matches_mode_at(simple_schedule):
    t_s, p_w = power_profile(simple_schedule, dt_s=25.0)
    for t, p in zip(t_s[:-1], p_w[:-1]):
        assert p == pytest.approx(simple_schedule.mode_at(t).power_w)


def test_power_profile_rejects_nonpositive_dt(simple_schedule):
    with pytest.raises(ValueError):
        power_profile(simple_schedule, dt_s=0.0)
    with pytest.raises(ValueError):
        power_profile(simple_schedule, dt_s=-5.0)


def test_power_profile_integral_matches_analytic_energy(simple_schedule):
    """Trapezoidal integration of a fine sample should closely match the
    exact analytic energy (piecewise-constant, so error should be tiny
    and driven only by the transition samples)."""
    t_s, p_w = power_profile(simple_schedule, dt_s=1.0)
    numeric_energy_j = np.trapezoid(p_w, t_s)
    analytic_energy_j = total_energy_j(simple_schedule)
    assert numeric_energy_j == pytest.approx(analytic_energy_j, rel=1e-3)
