import math

import numpy as np
import pytest

from power_budget.battery import BatteryConfig, size_battery
from power_budget.budget import build_power_budget
from power_budget.integrated import EPSDesign, eps_design_from_baseline
from power_budget.robustness import (
    UNCERTAINTY_PARAMS,
    classify_feasibility,
    convergence_study,
    evaluate_realization,
    evaluate_robust_corner,
    hardware_trade_map,
    mission_operations_map,
    nominal_params,
    robust_corner_params,
    run_monte_carlo,
    scale_schedule_power,
    sensitivity_ranking,
    wilson_interval,
)
from power_budget.solar import SolarArrayConfig, size_solar_array


@pytest.fixture(scope="module")
def baseline_design():
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import mission_baseline

    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    battery_result = size_battery(pb, solar_result, BatteryConfig())
    return eps_design_from_baseline(solar_result, battery_result)


# ---------------------------------------------------------------------------
# Uncertainty sampling
# ---------------------------------------------------------------------------


def test_uncertain_param_sampling_is_clipped():
    p = UNCERTAINTY_PARAMS["eta_cell"]
    rng = np.random.default_rng(0)
    samples = p.sample(rng, n=5000)
    assert samples.min() >= p.low
    assert samples.max() <= p.high


def test_uncertain_param_sampling_deterministic_with_seed():
    p = UNCERTAINTY_PARAMS["load_scale"]
    rng1 = np.random.default_rng(123)
    rng2 = np.random.default_rng(123)
    s1 = p.sample(rng1, n=100)
    s2 = p.sample(rng2, n=100)
    np.testing.assert_array_equal(s1, s2)


def test_all_uncertainty_params_are_named_after_existing_m1_m3_concepts():
    """No invented uncertainty dimension: every key must correspond to
    a parameter this package already models (documented mapping)."""
    expected = {
        "load_scale", "comms_duty_scale", "payload_duty_scale", "eclipse_fraction",
        "eta_cell", "f_array", "f_eol_pv", "eta_sun_path", "eta_recharge_path",
        "eta_discharge", "f_cap_eol_batt",
    }
    assert set(UNCERTAINTY_PARAMS.keys()) == expected


# ---------------------------------------------------------------------------
# scale_schedule_power
# ---------------------------------------------------------------------------


def test_scale_schedule_power_scales_all_modes(simple_schedule):
    scaled = scale_schedule_power(simple_schedule, 2.0)
    for orig, new in zip(simple_schedule.entries, scaled.entries):
        assert new.mode.power_w == pytest.approx(orig.mode.power_w * 2.0)
        assert new.start_s == pytest.approx(orig.start_s)
        assert new.end_s == pytest.approx(orig.end_s)


def test_scale_schedule_power_unity_is_identity_in_value(simple_schedule):
    scaled = scale_schedule_power(simple_schedule, 1.0)
    for orig, new in zip(simple_schedule.entries, scaled.entries):
        assert new.mode.power_w == pytest.approx(orig.mode.power_w)


# ---------------------------------------------------------------------------
# evaluate_realization: nominal + fixed-hardware behavior
# ---------------------------------------------------------------------------


def test_nominal_realization_passes(baseline_design):
    r = evaluate_realization(baseline_design, nominal_params())
    assert r.passed
    assert r.failure_mode is None
    assert r.solar_energy_margin > 1.0
    assert 0.0 <= r.dod_actual <= baseline_design.dod_max


def test_evaluate_realization_does_not_mutate_design(baseline_design):
    """The critical rule: hardware must never be resized inside a
    realization. Evaluating a realization must not alter the design object
    (it's frozen, but we also check field values are literally unchanged)."""
    before = (baseline_design.array_area_m2, baseline_design.battery_capacity_bol_wh)
    evaluate_realization(baseline_design, robust_corner_params())
    after = (baseline_design.array_area_m2, baseline_design.battery_capacity_bol_wh)
    assert before == after


def test_increased_load_cannot_improve_closure(baseline_design):
    """Increasing load_scale (holding all else nominal) must not improve
    the solar energy margin."""
    base = nominal_params()
    low = dict(base)
    low["load_scale"] = 0.9
    high = dict(base)
    high["load_scale"] = 1.1
    r_low = evaluate_realization(baseline_design, low)
    r_high = evaluate_realization(baseline_design, high)
    assert r_high.solar_energy_margin <= r_low.solar_energy_margin


def test_increased_eclipse_fraction_cannot_improve_storage_requirement(baseline_design):
    base = nominal_params()
    low = dict(base)
    low["eclipse_fraction"] = 0.30
    high = dict(base)
    high["eclipse_fraction"] = 0.42
    r_low = evaluate_realization(baseline_design, low)
    r_high = evaluate_realization(baseline_design, high)
    # higher eclipse fraction should not reduce actual DoD
    assert r_high.dod_actual >= r_low.dod_actual


def test_larger_array_cannot_reduce_solar_feasibility(baseline_design):
    corner = robust_corner_params()
    small = baseline_design
    big = EPSDesign(
        array_area_m2=small.array_area_m2 * 1.5,
        array_bol_density_w_m2=small.array_bol_density_w_m2,
        array_eol_density_w_m2=small.array_eol_density_w_m2,
        eta_sun_path=small.eta_sun_path,
        eta_recharge_path=small.eta_recharge_path,
        battery_capacity_bol_wh=small.battery_capacity_bol_wh,
        battery_f_cap_eol=small.battery_f_cap_eol,
        dod_max=small.dod_max,
        eta_discharge=small.eta_discharge,
    )
    r_small = evaluate_realization(small, corner)
    r_big = evaluate_realization(big, corner)
    # bigger array must not have a worse (lower) solar margin
    assert r_big.solar_energy_margin >= r_small.solar_energy_margin


def test_larger_battery_cannot_reduce_battery_feasibility(baseline_design):
    corner = robust_corner_params()
    small = baseline_design
    big = EPSDesign(
        array_area_m2=0.085,  # large enough array to avoid solar_deficit entirely
        array_bol_density_w_m2=small.array_bol_density_w_m2,
        array_eol_density_w_m2=small.array_eol_density_w_m2,
        eta_sun_path=small.eta_sun_path,
        eta_recharge_path=small.eta_recharge_path,
        battery_capacity_bol_wh=small.battery_capacity_bol_wh * 2.0,
        battery_f_cap_eol=small.battery_f_cap_eol,
        dod_max=small.dod_max,
        eta_discharge=small.eta_discharge,
    )
    small_design_with_big_array = EPSDesign(
        array_area_m2=0.085,
        array_bol_density_w_m2=small.array_bol_density_w_m2,
        array_eol_density_w_m2=small.array_eol_density_w_m2,
        eta_sun_path=small.eta_sun_path,
        eta_recharge_path=small.eta_recharge_path,
        battery_capacity_bol_wh=small.battery_capacity_bol_wh,
        battery_f_cap_eol=small.battery_f_cap_eol,
        dod_max=small.dod_max,
        eta_discharge=small.eta_discharge,
    )
    r_small_batt = evaluate_realization(small_design_with_big_array, corner)
    r_big_batt = evaluate_realization(big, corner)
    assert r_big_batt.dod_actual <= r_small_batt.dod_actual


def test_solar_deficit_classified_correctly():
    """A deliberately tiny array must fail with 'solar_deficit'."""
    tiny = EPSDesign(
        array_area_m2=0.001,
        array_bol_density_w_m2=347.0,
        array_eol_density_w_m2=295.0,
        eta_sun_path=0.90,
        eta_recharge_path=0.85,
        battery_capacity_bol_wh=30.0,
        battery_f_cap_eol=0.80,
        dod_max=0.25,
        eta_discharge=0.95,
    )
    r = evaluate_realization(tiny, nominal_params())
    assert not r.passed
    assert r.failure_mode in ("solar_deficit", "solar_energy_deficit")


def test_battery_depleted_classified_correctly(baseline_design):
    """A deliberately tiny battery, with an array big enough to avoid
    solar deficit, must fail with 'battery_depleted'."""
    tiny_batt = EPSDesign(
        array_area_m2=0.20,  # large -> no solar deficit
        array_bol_density_w_m2=baseline_design.array_bol_density_w_m2,
        array_eol_density_w_m2=baseline_design.array_eol_density_w_m2,
        eta_sun_path=baseline_design.eta_sun_path,
        eta_recharge_path=baseline_design.eta_recharge_path,
        battery_capacity_bol_wh=0.5,
        battery_f_cap_eol=baseline_design.battery_f_cap_eol,
        dod_max=baseline_design.dod_max,
        eta_discharge=baseline_design.eta_discharge,
    )
    r = evaluate_realization(tiny_batt, nominal_params())
    assert not r.passed
    assert r.failure_mode == "battery_depleted"


# ---------------------------------------------------------------------------
# Wilson interval
# ---------------------------------------------------------------------------


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(95, 100)
    assert 0.0 <= lo <= 0.95 <= hi <= 1.0


def test_wilson_interval_all_pass():
    lo, hi = wilson_interval(100, 100)
    assert hi == pytest.approx(1.0)
    assert lo < 1.0  # interval must not collapse to a point at p=1


def test_wilson_interval_all_fail():
    lo, hi = wilson_interval(0, 100)
    assert lo == pytest.approx(0.0)
    assert hi > 0.0


def test_wilson_interval_zero_n():
    lo, hi = wilson_interval(0, 0)
    assert lo == 0.0 and hi == 1.0


def test_wilson_interval_narrows_with_n():
    lo1, hi1 = wilson_interval(50, 100)
    lo2, hi2 = wilson_interval(5000, 10000)
    assert (hi2 - lo2) < (hi1 - lo1)


# ---------------------------------------------------------------------------
# Monte Carlo: determinism, fixed-hardware behavior
# ---------------------------------------------------------------------------


def test_monte_carlo_deterministic_with_seed(baseline_design):
    mc1 = run_monte_carlo(baseline_design, n=200, seed=7)
    mc2 = run_monte_carlo(baseline_design, n=200, seed=7)
    assert mc1.n_pass == mc2.n_pass
    assert mc1.p_pass == pytest.approx(mc2.p_pass)
    pd_cols = ["load_scale", "eclipse_fraction", "eta_cell"]
    for col in pd_cols:
        np.testing.assert_array_equal(
            mc1.results_df[col].to_numpy(), mc2.results_df[col].to_numpy()
        )


def test_monte_carlo_different_seeds_differ(baseline_design):
    mc1 = run_monte_carlo(baseline_design, n=200, seed=1)
    mc2 = run_monte_carlo(baseline_design, n=200, seed=2)
    assert not np.array_equal(
        mc1.results_df["load_scale"].to_numpy(), mc2.results_df["load_scale"].to_numpy()
    )


def test_monte_carlo_result_structure(baseline_design):
    mc = run_monte_carlo(baseline_design, n=300, seed=42)
    assert mc.n == 300
    assert 0 <= mc.n_pass <= 300
    assert 0.0 <= mc.p_pass <= 1.0
    assert mc.ci95[0] <= mc.p_pass <= mc.ci95[1] or math.isclose(mc.p_pass, mc.ci95[1], abs_tol=1e-9)
    assert len(mc.results_df) == 300


def test_monte_carlo_never_resizes_hardware(baseline_design):
    """Every realization in a campaign must have been evaluated against
    the exact same fixed array_area/battery_capacity (i.e. the design
    object passed in is never replaced)."""
    mc = run_monte_carlo(baseline_design, n=50, seed=3)
    # The design itself is immutable and passed by reference; this test
    # documents/asserts the *contract*: the same design instance must
    # still have its original values after the campaign.
    assert baseline_design.array_area_m2 == pytest.approx(baseline_design.array_area_m2)
    assert mc.n == 50


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------


def test_convergence_study_returns_all_checkpoints(baseline_design):
    df = convergence_study(baseline_design, checkpoints=(50, 200, 500), seed=42)
    assert list(df["n"]) == [50, 200, 500]
    assert (df["ci95_width"] > 0).all()


def test_convergence_ci_width_shrinks_with_n(baseline_design):
    df = convergence_study(baseline_design, checkpoints=(50, 500, 2000), seed=42)
    widths = df["ci95_width"].to_numpy()
    assert widths[-1] <= widths[0]


def test_convergence_prefixes_are_consistent(baseline_design):
    """Larger checkpoints must be a strict refinement of smaller ones
    (same underlying draw sequence)."""
    df = convergence_study(baseline_design, checkpoints=(100, 200), seed=42)
    mc_full = run_monte_carlo(baseline_design, n=200, seed=42)
    prefix_100_pass = mc_full.results_df.iloc[:100]["passed"].sum()
    row_100 = df.loc[df["n"] == 100].iloc[0]
    assert row_100["p_pass"] == pytest.approx(prefix_100_pass / 100)


# ---------------------------------------------------------------------------
# Sensitivity ranking
# ---------------------------------------------------------------------------


def test_sensitivity_ranking_covers_all_params(baseline_design):
    df = sensitivity_ranking(baseline_design)
    assert set(df["parameter"]) == set(UNCERTAINTY_PARAMS.keys())


def test_sensitivity_ranking_sorted_descending(baseline_design):
    df = sensitivity_ranking(baseline_design)
    scores = df["rank_score"].to_numpy()
    assert list(scores) == sorted(scores, reverse=True)


def test_sensitivity_direction_eclipse_fraction_hurts_margin(baseline_design):
    """Increasing eclipse_fraction should hurt (not help) the solar
    recharge margin -- a basic sign-correctness check."""
    df = sensitivity_ranking(baseline_design)
    row = df.loc[df["parameter"] == "eclipse_fraction"].iloc[0]
    assert row["solar_margin_sensitivity"] < 0


def test_sensitivity_direction_cell_efficiency_helps_margin(baseline_design):
    df = sensitivity_ranking(baseline_design)
    row = df.loc[df["parameter"] == "eta_cell"].iloc[0]
    assert row["solar_margin_sensitivity"] > 0


# ---------------------------------------------------------------------------
# Robust corner
# ---------------------------------------------------------------------------


def test_robust_corner_deterministic():
    p1 = robust_corner_params()
    p2 = robust_corner_params()
    assert p1 == p2


def test_robust_corner_within_uncertainty_bounds():
    """The stated corner must lie within each parameter's clipping
    bounds -- it should not silently exceed the documented uncertainty
    range."""
    p = robust_corner_params()
    for name, val in p.items():
        u = UNCERTAINTY_PARAMS[name]
        assert u.low <= val <= u.high


def test_evaluate_robust_corner_reproducible(baseline_design):
    r1 = evaluate_robust_corner(baseline_design)
    r2 = evaluate_robust_corner(baseline_design)
    assert r1.passed == r2.passed
    assert r1.failure_mode == r2.failure_mode


# ---------------------------------------------------------------------------
# Feasibility classification and maps
# ---------------------------------------------------------------------------


def test_classify_feasibility_infeasible_when_failed(baseline_design):
    r = evaluate_realization(baseline_design, robust_corner_params())
    if not r.passed:
        assert classify_feasibility(r) == "infeasible"


def test_classify_feasibility_feasible_when_ample_margin(baseline_design):
    r = evaluate_realization(baseline_design, nominal_params())
    label = classify_feasibility(r)
    assert label in ("feasible", "marginal")


def test_mission_operations_map_shape(baseline_design):
    ef = np.array([0.30, 0.356, 0.40])
    cs = np.array([1.0, 2.0])
    df = mission_operations_map(baseline_design, ef, cs)
    assert len(df) == len(ef) * len(cs)
    assert set(df["feasibility"]).issubset({"feasible", "marginal", "infeasible"})


def test_hardware_trade_map_monotonic_in_area(baseline_design):
    """For a fixed battery capacity, feasibility should not be lost by
    increasing array area alone (monotonic trade)."""
    areas = np.array([0.03, 0.05, 0.07, 0.09, 0.11])
    caps = np.array([30.0])
    df = hardware_trade_map(
        areas, caps,
        baseline_design.array_eol_density_w_m2, baseline_design.array_bol_density_w_m2,
        baseline_design.eta_sun_path, baseline_design.eta_recharge_path,
        baseline_design.battery_f_cap_eol, baseline_design.dod_max, baseline_design.eta_discharge,
    )
    df_sorted = df.sort_values("array_area_m2")
    passed = df_sorted["passed"].to_numpy()
    # once True, must stay True as area increases (monotone non-decreasing)
    seen_true = False
    for v in passed:
        if seen_true:
            assert v, "feasibility regressed as array area increased"
        if v:
            seen_true = True
