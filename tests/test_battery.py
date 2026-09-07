import pytest

from power_budget.battery import (
    BatteryConfig,
    battery_withdrawal_j,
    bol_nameplate_capacity_j,
    design_capacity_eol_j,
    raw_capacity_j,
    select_design_capacity_wh,
    simulate_orbit_soc,
    size_battery,
    verify_recharge_closure,
)
from power_budget.budget import build_power_budget
from power_budget.solar import SolarArrayConfig, size_solar_array

# ---------------------------------------------------------------------------
# BatteryConfig validation
# ---------------------------------------------------------------------------


def test_default_config_is_valid():
    cfg = BatteryConfig()
    assert 0 < cfg.eta_discharge <= 1
    assert 0 < cfg.dod_max <= 1
    assert cfg.capacity_margin >= 1.0
    assert 0 < cfg.f_cap_eol <= 1
    assert cfg.capacity_step_wh > 0


@pytest.mark.parametrize("field", ["eta_discharge", "dod_max", "f_cap_eol"])
@pytest.mark.parametrize("bad_value", [0.0, -0.1, 1.1])
def test_config_rejects_out_of_range_fields(field, bad_value):
    with pytest.raises(ValueError):
        BatteryConfig(**{field: bad_value})


def test_config_accepts_unit_bound_exactly_one():
    cfg = BatteryConfig(eta_discharge=1.0, dod_max=1.0, f_cap_eol=1.0)
    assert cfg.eta_discharge == 1.0


def test_config_rejects_margin_below_one():
    with pytest.raises(ValueError):
        BatteryConfig(capacity_margin=0.99)


def test_config_rejects_nonpositive_step():
    with pytest.raises(ValueError):
        BatteryConfig(capacity_step_wh=0.0)
    with pytest.raises(ValueError):
        BatteryConfig(capacity_step_wh=-1.0)


# ---------------------------------------------------------------------------
# Sizing chain formulas
# ---------------------------------------------------------------------------


def test_battery_withdrawal_formula():
    cfg = BatteryConfig(eta_discharge=0.9)
    assert battery_withdrawal_j(9000.0, cfg) == pytest.approx(10000.0)


def test_battery_withdrawal_rejects_negative_energy():
    with pytest.raises(ValueError):
        battery_withdrawal_j(-1.0, BatteryConfig())


def test_raw_capacity_formula():
    cfg = BatteryConfig(dod_max=0.25)
    assert raw_capacity_j(1000.0, cfg) == pytest.approx(4000.0)


def test_raw_capacity_rejects_negative_withdrawal():
    with pytest.raises(ValueError):
        raw_capacity_j(-1.0, BatteryConfig())


def test_design_capacity_eol_is_margin_times_raw():
    cfg = BatteryConfig(capacity_margin=1.3)
    assert design_capacity_eol_j(1000.0, cfg) == pytest.approx(1300.0)


def test_design_capacity_equals_raw_at_unity_margin():
    cfg = BatteryConfig(capacity_margin=1.0)
    assert design_capacity_eol_j(500.0, cfg) == pytest.approx(500.0)


def test_bol_nameplate_formula():
    cfg = BatteryConfig(f_cap_eol=0.8)
    assert bol_nameplate_capacity_j(800.0, cfg) == pytest.approx(1000.0)


def test_bol_nameplate_equals_design_when_no_fade():
    cfg = BatteryConfig(f_cap_eol=1.0)
    assert bol_nameplate_capacity_j(500.0, cfg) == pytest.approx(500.0)


def test_dod_and_margin_are_kept_separate():
    """DoD must not implicitly absorb design margin."""
    withdrawal_j = 5000.0
    cfg_no_margin = BatteryConfig(capacity_margin=1.0, dod_max=0.25)
    cfg_with_margin = BatteryConfig(capacity_margin=1.25, dod_max=0.25)
    raw_a = raw_capacity_j(withdrawal_j, cfg_no_margin)
    raw_b = raw_capacity_j(withdrawal_j, cfg_with_margin)
    # raw capacity must be identical regardless of capacity_margin
    assert raw_a == pytest.approx(raw_b)


# ---------------------------------------------------------------------------
# Selected design capacity rounding
# ---------------------------------------------------------------------------


def test_select_design_capacity_rounds_up_to_step():
    cfg = BatteryConfig(capacity_step_wh=5.0)
    assert select_design_capacity_wh(24.7, cfg) == pytest.approx(25.0)
    assert select_design_capacity_wh(25.0, cfg) == pytest.approx(25.0)
    assert select_design_capacity_wh(25.01, cfg) == pytest.approx(30.0)


def test_select_design_capacity_never_below_minimum():
    cfg = BatteryConfig(capacity_step_wh=5.0)
    for val in [0.1, 4.9, 5.0, 5.1, 12.3, 100.0]:
        selected = select_design_capacity_wh(val, cfg)
        assert selected >= val - 1e-9


def test_select_design_capacity_rejects_negative():
    with pytest.raises(ValueError):
        select_design_capacity_wh(-1.0, BatteryConfig())


# ---------------------------------------------------------------------------
# Recharge closure
# ---------------------------------------------------------------------------


def test_recharge_closure_exact_boundary():
    cfg = SolarArrayConfig(eta_sun_path=0.9, eta_recharge_path=0.85)
    e_sun_j, t_sun_s = 9000.0, 1000.0
    p_design_w = 20.0
    available = max(p_design_w * t_sun_s - e_sun_j / 0.9, 0.0) * 0.85
    result = verify_recharge_closure(e_sun_j, t_sun_s, p_design_w, available, cfg)
    assert result.closes
    assert result.margin_fraction == pytest.approx(0.0, abs=1e-9)


def test_recharge_closure_fails_when_undersized():
    cfg = SolarArrayConfig()
    result = verify_recharge_closure(9000.0, 1000.0, 20.0, 1e9, cfg)
    assert not result.closes
    assert result.margin_fraction < 0


def test_recharge_closure_rejects_nonpositive_t_sun():
    with pytest.raises(ValueError):
        verify_recharge_closure(100.0, 0.0, 20.0, 50.0, SolarArrayConfig())


# ---------------------------------------------------------------------------
# End-to-end sizing against the fixture schedule
# ---------------------------------------------------------------------------


def test_size_battery_end_to_end(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    battery_result = size_battery(pb, solar_result, BatteryConfig())

    assert battery_result.e_eclipse_j == pytest.approx(pb.phase_energy["eclipse"].energy_j)
    assert battery_result.withdrawal_j > battery_result.e_eclipse_j  # discharge loss
    assert battery_result.raw_capacity_j > 0
    assert battery_result.design_capacity_eol_j > battery_result.raw_capacity_j
    assert battery_result.bol_nameplate_capacity_j > battery_result.design_capacity_eol_j
    assert battery_result.selected_capacity_wh * 3600.0 >= battery_result.bol_nameplate_capacity_j - 1e-6
    assert 0 < battery_result.actual_dod <= 1.0
    # selected capacity carries margin -> actual DoD should be below dod_max
    assert battery_result.actual_dod < BatteryConfig().dod_max


def test_baseline_recharge_closes(mission_power_budget_and_solar):
    pb, solar_result = mission_power_budget_and_solar
    battery_result = size_battery(pb, solar_result, BatteryConfig())
    assert battery_result.closure.closes
    assert battery_result.closure.margin_fraction > 0


def test_baseline_soc_profile_bounds(mission_power_budget_and_solar):
    pb, solar_result = mission_power_budget_and_solar
    battery_result = size_battery(pb, solar_result, BatteryConfig())
    profile = battery_result.soc_profile
    assert all(0.0 <= s <= 1.0 + 1e-9 for s in profile.soc)
    assert profile.min_soc == pytest.approx(min(profile.soc))
    assert profile.min_soc < 1.0
    # periodic steady state: final SOC should return to initial SOC
    assert profile.final_soc == pytest.approx(profile.initial_soc, abs=1e-6)


def test_baseline_recharge_time_is_within_sunlight_and_positive(mission_power_budget_and_solar):
    pb, solar_result = mission_power_budget_and_solar
    battery_result = size_battery(pb, solar_result, BatteryConfig())
    profile = battery_result.soc_profile
    assert profile.t_recharge_s is not None
    assert 0.0 < profile.t_recharge_s <= solar_result.t_sun_s + 1e-6


# ---------------------------------------------------------------------------
# SOC/DoD relationship, bounds
# ---------------------------------------------------------------------------


def test_soc_capacity_relationship(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    capacity_j = 100_000.0
    profile = simulate_orbit_soc(
        schedule=simple_schedule,
        orbit=orbit,
        p_sa_design_w=solar_result.p_sa_design_w,
        solar_config=solar_result.config,
        battery_config=BatteryConfig(),
        capacity_j=capacity_j,
        initial_soc=1.0,
    )
    # DoD = 1 - SOC, starting from full charge
    for s in profile.soc:
        dod = 1.0 - s
        assert 0.0 <= dod <= 1.0 + 1e-9


def test_simulate_orbit_soc_rejects_bad_capacity(simple_schedule, orbit):
    with pytest.raises(ValueError):
        simulate_orbit_soc(
            simple_schedule, orbit, 20.0, SolarArrayConfig(), BatteryConfig(), capacity_j=0.0
        )


def test_simulate_orbit_soc_rejects_undersized_battery(simple_schedule, orbit):
    # A tiny capacity cannot survive the eclipse discharge without going negative.
    with pytest.raises(ValueError, match="undersized"):
        simulate_orbit_soc(
            simple_schedule,
            orbit,
            p_sa_design_w=20.0,
            solar_config=SolarArrayConfig(),
            battery_config=BatteryConfig(),
            capacity_j=1.0,
            initial_soc=0.5,
        )


def test_simulate_orbit_soc_rejects_array_deficit_in_sunlight(simple_schedule, orbit):
    with pytest.raises(ValueError, match="exceeds design array output"):
        simulate_orbit_soc(
            simple_schedule,
            orbit,
            p_sa_design_w=1.0,  # far too small to cover sunlight loads
            solar_config=SolarArrayConfig(),
            battery_config=BatteryConfig(),
            capacity_j=1_000_000.0,
            initial_soc=0.5,
        )


# ---------------------------------------------------------------------------
# Eclipse discharge / sunlight recharge direct checks
# ---------------------------------------------------------------------------


def test_eclipse_only_discharges_battery():
    """A fully-sunlit orbit (no eclipse) should never discharge the battery."""
    from power_budget.modes import Mode
    from power_budget.orbit import OrbitGeometry
    from power_budget.schedule import OrbitSchedule, ScheduleEntry

    period_s = 6000.0
    nominal = Mode("nominal", 5.0)
    orbit_geom = OrbitGeometry(period_s=period_s, eclipse_fraction=0.0)
    sched = OrbitSchedule(
        entries=(ScheduleEntry(nominal, 0.0, period_s),), orbit_period_s=period_s
    )
    profile = simulate_orbit_soc(
        sched, orbit_geom, p_sa_design_w=20.0, solar_config=SolarArrayConfig(),
        battery_config=BatteryConfig(), capacity_j=1_000_000.0, initial_soc=0.5,
    )
    # SOC should only increase (charging) or stay clipped at full; no discharge occurs
    assert all(b >= a - 1e-9 for a, b in zip(profile.soc, profile.soc[1:]))


# ---------------------------------------------------------------------------
# Monotonicity / sensitivity direction checks
# ---------------------------------------------------------------------------


def test_higher_eclipse_energy_increases_withdrawal_and_capacity():
    cfg = BatteryConfig()
    w_low = battery_withdrawal_j(1000.0, cfg)
    w_high = battery_withdrawal_j(5000.0, cfg)
    assert w_high > w_low
    assert raw_capacity_j(w_high, cfg) > raw_capacity_j(w_low, cfg)


def test_dod_inverse_scaling():
    withdrawal_j = 5000.0
    cfg_low = BatteryConfig(dod_max=0.15)
    cfg_high = BatteryConfig(dod_max=0.30)
    cap_low_dod = raw_capacity_j(withdrawal_j, cfg_low)
    cap_high_dod = raw_capacity_j(withdrawal_j, cfg_high)
    # halving dod_max should double required capacity (C ~ 1/DoD_max)
    assert cap_low_dod == pytest.approx(2.0 * cap_high_dod, rel=1e-9)


def test_discharge_efficiency_inverse_scaling():
    e_eclipse_j = 5000.0
    cfg_low = BatteryConfig(eta_discharge=0.60)
    cfg_high = BatteryConfig(eta_discharge=0.90)
    w_low = battery_withdrawal_j(e_eclipse_j, cfg_low)
    w_high = battery_withdrawal_j(e_eclipse_j, cfg_high)
    assert w_low > w_high
    cap_low = raw_capacity_j(w_low, cfg_low)
    cap_high = raw_capacity_j(w_high, cfg_high)
    assert cap_low > cap_high


def test_eol_retention_inverse_scaling():
    design_eol_j_ = 10000.0
    cfg_full = BatteryConfig(f_cap_eol=1.0)
    cfg_degraded = BatteryConfig(f_cap_eol=0.5)
    bol_full = bol_nameplate_capacity_j(design_eol_j_, cfg_full)
    bol_degraded = bol_nameplate_capacity_j(design_eol_j_, cfg_degraded)
    # halving f_cap_eol should double required BOL capacity
    assert bol_degraded == pytest.approx(2.0 * bol_full, rel=1e-9)


def test_capacity_margin_linear_scaling():
    raw_j_ = 10000.0
    values = []
    for sf in (1.0, 1.1, 1.2, 1.3):
        cfg = BatteryConfig(capacity_margin=sf)
        values.append(design_capacity_eol_j(raw_j_, cfg))
    for i in range(1, len(values)):
        assert values[i] / values[0] == pytest.approx([1.0, 1.1, 1.2, 1.3][i], rel=1e-9)


@pytest.mark.parametrize("f_e", [0.20, 0.30, 0.356, 0.40, 0.45])
def test_eclipse_fraction_sweep_valid(f_e):
    from power_budget.modes import Mode
    from power_budget.orbit import OrbitGeometry
    from power_budget.schedule import OrbitSchedule, ScheduleEntry

    period_s = 5676.0
    nominal = Mode("nominal", 6.8)
    orbit_geom = OrbitGeometry(period_s=period_s, eclipse_fraction=f_e)
    sched = OrbitSchedule(
        entries=(ScheduleEntry(nominal, 0.0, period_s),), orbit_period_s=period_s
    )
    pb = build_power_budget(sched, orbit_geom)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    battery_result = size_battery(pb, solar_result, BatteryConfig())
    assert battery_result.raw_capacity_j > 0
    assert battery_result.closure.closes


def test_eclipse_fraction_monotonic_capacity():
    from power_budget.modes import Mode
    from power_budget.orbit import OrbitGeometry
    from power_budget.schedule import OrbitSchedule, ScheduleEntry

    period_s = 5676.0
    nominal = Mode("nominal", 6.8)
    fractions = [0.20, 0.30, 0.356, 0.40, 0.45]
    caps = []
    for f_e in fractions:
        orbit_geom = OrbitGeometry(period_s=period_s, eclipse_fraction=f_e)
        sched = OrbitSchedule(
            entries=(ScheduleEntry(nominal, 0.0, period_s),), orbit_period_s=period_s
        )
        pb = build_power_budget(sched, orbit_geom)
        solar_result = size_solar_array(pb, SolarArrayConfig())
        battery_result = size_battery(pb, solar_result, BatteryConfig())
        caps.append(battery_result.raw_capacity_j)
    assert caps == sorted(caps)
    assert all(b > a for a, b in zip(caps, caps[1:]))


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------


@pytest.fixture
def mission_power_budget_and_solar():
    """Baseline mission PowerBudget + M2 solar sizing, for battery tests."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import mission_baseline

    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    return pb, solar_result
