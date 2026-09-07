import pytest

from power_budget.budget import build_power_budget
from power_budget.solar import (
    SOLAR_CONSTANT_W_M2,
    SolarArrayConfig,
    bol_power_density_w_m2,
    eol_power_density_w_m2,
    required_array_area_m2,
    required_array_power_design_w,
    required_array_power_raw_w,
    size_solar_array,
    verify_energy_closure,
)

# ---------------------------------------------------------------------------
# SolarArrayConfig validation
# ---------------------------------------------------------------------------


def test_default_config_is_valid():
    cfg = SolarArrayConfig()
    assert cfg.s0_w_m2 == SOLAR_CONSTANT_W_M2
    assert 0 < cfg.eta_cell <= 1
    assert cfg.design_margin >= 1.0


@pytest.mark.parametrize("field", ["eta_cell", "f_array", "f_eol", "eta_sun_path", "eta_recharge_path"])
@pytest.mark.parametrize("bad_value", [0.0, -0.1, 1.1])
def test_config_rejects_out_of_range_efficiencies(field, bad_value):
    with pytest.raises(ValueError):
        SolarArrayConfig(**{field: bad_value})


def test_config_accepts_efficiency_exactly_one():
    cfg = SolarArrayConfig(eta_cell=1.0, f_array=1.0, f_eol=1.0, eta_sun_path=1.0, eta_recharge_path=1.0)
    assert cfg.eta_cell == 1.0


def test_config_rejects_nonpositive_s0():
    with pytest.raises(ValueError):
        SolarArrayConfig(s0_w_m2=0.0)
    with pytest.raises(ValueError):
        SolarArrayConfig(s0_w_m2=-100.0)


def test_config_rejects_margin_below_one():
    with pytest.raises(ValueError):
        SolarArrayConfig(design_margin=0.99)


def test_config_accepts_margin_exactly_one():
    cfg = SolarArrayConfig(design_margin=1.0)
    assert cfg.design_margin == 1.0


# ---------------------------------------------------------------------------
# Power-density chain (BOL / EOL)
# ---------------------------------------------------------------------------


def test_bol_power_density_formula():
    cfg = SolarArrayConfig(s0_w_m2=1361.0, eta_cell=0.30, f_array=0.85)
    expected = 1361.0 * 0.30 * 0.85
    assert bol_power_density_w_m2(cfg) == pytest.approx(expected)


def test_eol_power_density_is_bol_times_feol():
    cfg = SolarArrayConfig(f_eol=0.8)
    bol = bol_power_density_w_m2(cfg)
    eol = eol_power_density_w_m2(cfg)
    assert eol == pytest.approx(bol * 0.8)


def test_eol_density_less_than_or_equal_bol():
    cfg = SolarArrayConfig(f_eol=0.85)
    assert eol_power_density_w_m2(cfg) <= bol_power_density_w_m2(cfg)


def test_eol_equals_bol_when_feol_is_one():
    cfg = SolarArrayConfig(f_eol=1.0)
    assert eol_power_density_w_m2(cfg) == pytest.approx(bol_power_density_w_m2(cfg))


# ---------------------------------------------------------------------------
# Raw / design power requirement
# ---------------------------------------------------------------------------


def test_required_array_power_raw_formula():
    cfg = SolarArrayConfig(eta_sun_path=0.9, eta_recharge_path=0.8)
    e_sun_j = 9000.0
    e_ecl_j = 4000.0
    t_sun_s = 1000.0
    expected = (e_sun_j / 0.9 + e_ecl_j / 0.8) / t_sun_s
    assert required_array_power_raw_w(e_sun_j, e_ecl_j, t_sun_s, cfg) == pytest.approx(expected)


def test_required_array_power_raw_rejects_nonpositive_t_sun():
    cfg = SolarArrayConfig()
    with pytest.raises(ValueError):
        required_array_power_raw_w(100.0, 50.0, 0.0, cfg)
    with pytest.raises(ValueError):
        required_array_power_raw_w(100.0, 50.0, -10.0, cfg)


def test_required_array_power_raw_rejects_negative_energy():
    cfg = SolarArrayConfig()
    with pytest.raises(ValueError):
        required_array_power_raw_w(-1.0, 50.0, 100.0, cfg)
    with pytest.raises(ValueError):
        required_array_power_raw_w(100.0, -1.0, 100.0, cfg)


def test_design_power_is_margin_times_raw():
    cfg = SolarArrayConfig(design_margin=1.3)
    raw = 10.0
    assert required_array_power_design_w(raw, cfg) == pytest.approx(13.0)


def test_design_power_equals_raw_at_unity_margin():
    cfg = SolarArrayConfig(design_margin=1.0)
    assert required_array_power_design_w(20.0, cfg) == pytest.approx(20.0)


def test_raw_and_design_are_kept_separate_not_conflated():
    """Design margin must not be hidden inside the raw calculation."""
    cfg_no_margin = SolarArrayConfig(design_margin=1.0)
    cfg_with_margin = SolarArrayConfig(design_margin=1.25)
    raw_no_margin = required_array_power_raw_w(9000.0, 4000.0, 1000.0, cfg_no_margin)
    raw_with_margin = required_array_power_raw_w(9000.0, 4000.0, 1000.0, cfg_with_margin)
    # raw requirement must be identical regardless of design_margin --
    # margin only enters at required_array_power_design_w.
    assert raw_no_margin == pytest.approx(raw_with_margin)


# ---------------------------------------------------------------------------
# Area sizing
# ---------------------------------------------------------------------------


def test_required_area_formula():
    assert required_array_area_m2(design_power_w=100.0, eol_density_w_m2_=250.0) == pytest.approx(0.4)


def test_required_area_positive_for_positive_power():
    area = required_array_area_m2(design_power_w=50.0, eol_density_w_m2_=300.0)
    assert area > 0


def test_required_area_rejects_nonpositive_density():
    with pytest.raises(ValueError):
        required_array_area_m2(design_power_w=10.0, eol_density_w_m2_=0.0)
    with pytest.raises(ValueError):
        required_array_area_m2(design_power_w=10.0, eol_density_w_m2_=-5.0)


def test_required_area_rejects_negative_power():
    with pytest.raises(ValueError):
        required_array_area_m2(design_power_w=-10.0, eol_density_w_m2_=100.0)


# ---------------------------------------------------------------------------
# Energy closure
# ---------------------------------------------------------------------------


def test_energy_closure_exact_at_unity_margin():
    cfg = SolarArrayConfig(design_margin=1.0, eta_sun_path=0.9, eta_recharge_path=0.85)
    e_sun_j, e_ecl_j, t_sun_s = 9000.0, 4000.0, 1000.0
    p_raw = required_array_power_raw_w(e_sun_j, e_ecl_j, t_sun_s, cfg)
    p_design = required_array_power_design_w(p_raw, cfg)
    closure = verify_energy_closure(e_sun_j, e_ecl_j, t_sun_s, p_design, cfg)
    assert closure.closes
    assert closure.margin_fraction == pytest.approx(0.0, abs=1e-9)
    assert closure.generated_j == pytest.approx(closure.required_raw_j)


def test_energy_closure_margin_fraction_matches_design_margin():
    cfg = SolarArrayConfig(design_margin=1.25)
    e_sun_j, e_ecl_j, t_sun_s = 9000.0, 4000.0, 1000.0
    p_raw = required_array_power_raw_w(e_sun_j, e_ecl_j, t_sun_s, cfg)
    p_design = required_array_power_design_w(p_raw, cfg)
    closure = verify_energy_closure(e_sun_j, e_ecl_j, t_sun_s, p_design, cfg)
    assert closure.closes
    assert closure.margin_fraction == pytest.approx(0.25, rel=1e-6)


def test_energy_closure_fails_when_undersized():
    cfg = SolarArrayConfig()
    e_sun_j, e_ecl_j, t_sun_s = 9000.0, 4000.0, 1000.0
    undersized_power_w = 1.0  # deliberately far too small
    closure = verify_energy_closure(e_sun_j, e_ecl_j, t_sun_s, undersized_power_w, cfg)
    assert not closure.closes
    assert closure.margin_fraction < 0


# ---------------------------------------------------------------------------
# End-to-end sizing against the Milestone-1 baseline schedule/orbit
# ---------------------------------------------------------------------------


def test_size_solar_array_end_to_end(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    cfg = SolarArrayConfig()
    result = size_solar_array(pb, cfg)

    assert result.t_sun_s == pytest.approx(pb.phase_energy["sunlight"].duration_s)
    assert result.e_sun_j == pytest.approx(pb.phase_energy["sunlight"].energy_j)
    assert result.e_eclipse_j == pytest.approx(pb.phase_energy["eclipse"].energy_j)

    # design power must exceed raw power whenever margin > 1
    assert result.p_sa_design_w > result.p_sa_raw_w

    # EOL density must not exceed BOL density
    assert result.eol_density_w_m2 <= result.bol_density_w_m2

    # area must be positive
    assert result.area_m2 > 0

    # closure must hold for the sized design
    assert result.closure.closes
    assert result.closure.margin_fraction == pytest.approx(cfg.design_margin - 1.0, rel=1e-6)


def test_raw_to_avg_ratio_exceeds_one(simple_schedule, orbit):
    """Central Milestone-2 finding: eclipse recharge + losses push the
    raw array requirement above naive orbit-average-power sizing."""
    pb = build_power_budget(simple_schedule, orbit)
    result = size_solar_array(pb, SolarArrayConfig())
    assert result.avg_power_w == pytest.approx(pb.orbit_average_power_w)
    assert result.raw_to_avg_ratio > 1.0
    assert result.p_sa_raw_w > result.avg_power_w


# ---------------------------------------------------------------------------
# Monotonicity / sensitivity direction checks
# ---------------------------------------------------------------------------


def test_higher_eclipse_energy_increases_raw_power():
    cfg = SolarArrayConfig()
    t_sun_s = 1000.0
    e_sun_j = 5000.0
    p_low = required_array_power_raw_w(e_sun_j, 1000.0, t_sun_s, cfg)
    p_high = required_array_power_raw_w(e_sun_j, 5000.0, t_sun_s, cfg)
    assert p_high > p_low


def test_worse_recharge_efficiency_increases_raw_power_and_area():
    e_sun_j, e_ecl_j, t_sun_s = 9000.0, 4000.0, 1000.0
    cfg_good = SolarArrayConfig(eta_recharge_path=0.95)
    cfg_bad = SolarArrayConfig(eta_recharge_path=0.60)
    p_good = required_array_power_raw_w(e_sun_j, e_ecl_j, t_sun_s, cfg_good)
    p_bad = required_array_power_raw_w(e_sun_j, e_ecl_j, t_sun_s, cfg_bad)
    assert p_bad > p_good

    area_good = required_array_area_m2(
        required_array_power_design_w(p_good, cfg_good), eol_power_density_w_m2(cfg_good)
    )
    area_bad = required_array_area_m2(
        required_array_power_design_w(p_bad, cfg_bad), eol_power_density_w_m2(cfg_bad)
    )
    assert area_bad > area_good


def test_eol_degradation_scales_area_inversely():
    design_power_w = 20.0
    cfg_full = SolarArrayConfig(f_eol=1.0)
    cfg_degraded = SolarArrayConfig(f_eol=0.5)
    area_full = required_array_area_m2(design_power_w, eol_power_density_w_m2(cfg_full))
    area_degraded = required_array_area_m2(design_power_w, eol_power_density_w_m2(cfg_degraded))
    # halving f_eol should double the required area (A ~ 1/f_eol)
    assert area_degraded == pytest.approx(2.0 * area_full, rel=1e-9)


def test_cell_efficiency_scales_area_inversely():
    design_power_w = 20.0
    cfg_low = SolarArrayConfig(eta_cell=0.15)
    cfg_high = SolarArrayConfig(eta_cell=0.30)
    area_low = required_array_area_m2(design_power_w, eol_power_density_w_m2(cfg_low))
    area_high = required_array_area_m2(design_power_w, eol_power_density_w_m2(cfg_high))
    # doubling eta_cell should halve the required area (A ~ 1/eta_cell)
    assert area_low == pytest.approx(2.0 * area_high, rel=1e-9)


def test_load_margin_scales_power_and_area_linearly():
    e_sun_j, e_ecl_j, t_sun_s = 9000.0, 4000.0, 1000.0
    cfg_base = SolarArrayConfig(design_margin=1.0)
    raw = required_array_power_raw_w(e_sun_j, e_ecl_j, t_sun_s, cfg_base)
    eol = eol_power_density_w_m2(cfg_base)

    powers = []
    areas = []
    for sf in (1.0, 1.1, 1.2, 1.3):
        cfg = SolarArrayConfig(design_margin=sf)
        p_design = required_array_power_design_w(raw, cfg)
        powers.append(p_design)
        areas.append(required_array_area_m2(p_design, eol))

    # both should scale linearly with SF_P
    for i in range(1, len(powers)):
        assert powers[i] / powers[0] == pytest.approx([1.0, 1.1, 1.2, 1.3][i], rel=1e-9)
        assert areas[i] / areas[0] == pytest.approx([1.0, 1.1, 1.2, 1.3][i], rel=1e-9)


@pytest.mark.parametrize("f_e", [0.20, 0.30, 0.356, 0.40, 0.45])
def test_eclipse_fraction_sweep_monotonic_area(f_e):
    """Smoke test that each eclipse fraction in the milestone's sweep range
    produces a valid, positive sizing result (full monotonicity sequence
    is checked in test_eclipse_fraction_monotonic_sequence)."""
    from power_budget.orbit import OrbitGeometry
    from power_budget.schedule import OrbitSchedule, ScheduleEntry
    from power_budget.modes import Mode

    period_s = 5676.0
    nominal = Mode("nominal", 6.8)
    orbit_geom = OrbitGeometry(period_s=period_s, eclipse_fraction=f_e)
    sched = OrbitSchedule(
        entries=(ScheduleEntry(nominal, 0.0, period_s),), orbit_period_s=period_s
    )
    pb = build_power_budget(sched, orbit_geom)
    result = size_solar_array(pb, SolarArrayConfig())
    assert result.area_m2 > 0
    assert result.closure.closes


def test_eclipse_fraction_monotonic_sequence():
    """As eclipse fraction increases (all else equal), sunlight time
    shrinks and eclipse energy grows, so required array power and area
    must increase monotonically."""
    from power_budget.orbit import OrbitGeometry
    from power_budget.schedule import OrbitSchedule, ScheduleEntry
    from power_budget.modes import Mode

    period_s = 5676.0
    nominal = Mode("nominal", 6.8)
    fractions = [0.20, 0.30, 0.356, 0.40, 0.45]
    powers = []
    areas = []
    for f_e in fractions:
        orbit_geom = OrbitGeometry(period_s=period_s, eclipse_fraction=f_e)
        sched = OrbitSchedule(
            entries=(ScheduleEntry(nominal, 0.0, period_s),), orbit_period_s=period_s
        )
        pb = build_power_budget(sched, orbit_geom)
        result = size_solar_array(pb, SolarArrayConfig())
        powers.append(result.p_sa_raw_w)
        areas.append(result.area_m2)

    assert powers == sorted(powers)
    assert areas == sorted(areas)
    # strictly increasing (no ties) for this monotone load model
    assert all(b > a for a, b in zip(powers, powers[1:]))
    assert all(b > a for a, b in zip(areas, areas[1:]))
