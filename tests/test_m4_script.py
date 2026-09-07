"""Regression / integration tests for the Milestone-4 script
(scripts/final_eps_study.py): deterministic headline numbers and the
escalation derivation, mirroring tests/test_m2_script.py and
tests/test_m3_script.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from power_budget.budget import build_power_budget  # noqa: E402
from power_budget.integrated import compute_margins, requirement_from_power_budget  # noqa: E402
from power_budget.robustness import evaluate_robust_corner, run_monte_carlo  # noqa: E402

import mission_baseline  # noqa: E402
import final_eps_study as m4  # noqa: E402


# ---------------------------------------------------------------------------
# M1/M2/M3 regression
# ---------------------------------------------------------------------------


def test_m1_baseline_numbers_unchanged():
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    assert pb.orbit_average_power_w == pytest.approx(8.79, abs=5e-3)
    assert pb.peak_power_w == pytest.approx(14.50, abs=5e-3)
    assert pb.phase_energy["eclipse"].energy_j / 3600.0 == pytest.approx(4.38, abs=5e-3)


def test_minimum_design_matches_m2_m3():
    minimum_design, _ = m4.compute_baseline_design()
    assert minimum_design.array_area_m2 == pytest.approx(0.0654, abs=5e-4)
    assert minimum_design.battery_capacity_bol_wh == pytest.approx(30.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Escalation derivation
# ---------------------------------------------------------------------------


def test_final_design_values():
    assert m4.FINAL_ARRAY_AREA_M2 == pytest.approx(0.085)
    assert m4.FINAL_BATTERY_CAPACITY_WH == pytest.approx(35.0)


def test_minimum_design_fails_robust_corner():
    minimum_design, _ = m4.compute_baseline_design()
    r = evaluate_robust_corner(minimum_design)
    assert not r.passed


def test_final_design_passes_robust_corner():
    _, final_design = m4.compute_baseline_design()
    r = evaluate_robust_corner(final_design)
    assert r.passed
    assert r.failure_mode is None


def test_escalation_derivation_table_contains_baseline_and_final():
    minimum_design, final_design = m4.compute_baseline_design()
    df = m4.derive_escalation(minimum_design)
    min_row = df[
        (df["array_area_m2"] == minimum_design.array_area_m2)
        & (df["battery_capacity_wh"] == minimum_design.battery_capacity_bol_wh)
    ].iloc[0]
    assert not min_row["robust_corner_passes"]

    final_row = df[
        (df["array_area_m2"] == m4.FINAL_ARRAY_AREA_M2)
        & (df["battery_capacity_wh"] == m4.FINAL_BATTERY_CAPACITY_WH)
    ].iloc[0]
    assert final_row["robust_corner_passes"]


# ---------------------------------------------------------------------------
# Deterministic headline numbers
# ---------------------------------------------------------------------------


def test_m4_nominal_margins_deterministic():
    minimum_design, final_design = m4.compute_baseline_design()
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    req = requirement_from_power_budget(pb)
    margins = compute_margins(final_design, req, t_recharge_s=None)
    assert margins.solar_energy_margin == pytest.approx(1.624, abs=0.01)
    assert margins.array_power_margin == pytest.approx(1.624, abs=0.01)
    assert margins.battery_energy_margin == pytest.approx(1.517, abs=0.01)


def test_m4_monte_carlo_deterministic():
    _, final_design = m4.compute_baseline_design()
    mc = run_monte_carlo(final_design, n=m4.N_MC, seed=m4.SEED)
    assert mc.p_pass == pytest.approx(0.9999, abs=0.002)
    assert mc.ci95[0] > 0.99


def test_m4_monte_carlo_reproducible_across_runs():
    _, final_design = m4.compute_baseline_design()
    mc1 = run_monte_carlo(final_design, n=500, seed=m4.SEED)
    mc2 = run_monte_carlo(final_design, n=500, seed=m4.SEED)
    assert mc1.n_pass == mc2.n_pass


# ---------------------------------------------------------------------------
# Escalation is minimal and justified: array-only or battery-only fixes
# are each insufficient at the robust corner (both were genuinely needed)
# ---------------------------------------------------------------------------


def test_array_only_escalation_insufficient_for_dod():
    from power_budget.integrated import EPSDesign
    from power_budget.robustness import robust_corner_params, evaluate_realization

    minimum_design, _ = m4.compute_baseline_design()
    corner = robust_corner_params()
    array_only = EPSDesign(
        array_area_m2=m4.FINAL_ARRAY_AREA_M2,
        array_bol_density_w_m2=minimum_design.array_bol_density_w_m2,
        array_eol_density_w_m2=minimum_design.array_eol_density_w_m2,
        eta_sun_path=minimum_design.eta_sun_path,
        eta_recharge_path=minimum_design.eta_recharge_path,
        battery_capacity_bol_wh=minimum_design.battery_capacity_bol_wh,  # unchanged
        battery_f_cap_eol=minimum_design.battery_f_cap_eol,
        dod_max=minimum_design.dod_max,
        eta_discharge=minimum_design.eta_discharge,
    )
    r = evaluate_realization(array_only, corner)
    assert not r.passed
    assert r.failure_mode == "dod_exceeded"


def test_battery_only_escalation_insufficient_for_solar():
    from power_budget.integrated import EPSDesign
    from power_budget.robustness import robust_corner_params, evaluate_realization

    minimum_design, _ = m4.compute_baseline_design()
    corner = robust_corner_params()
    battery_only = EPSDesign(
        array_area_m2=minimum_design.array_area_m2,  # unchanged
        array_bol_density_w_m2=minimum_design.array_bol_density_w_m2,
        array_eol_density_w_m2=minimum_design.array_eol_density_w_m2,
        eta_sun_path=minimum_design.eta_sun_path,
        eta_recharge_path=minimum_design.eta_recharge_path,
        battery_capacity_bol_wh=m4.FINAL_BATTERY_CAPACITY_WH,
        battery_f_cap_eol=minimum_design.battery_f_cap_eol,
        dod_max=minimum_design.dod_max,
        eta_discharge=minimum_design.eta_discharge,
    )
    r = evaluate_realization(battery_only, corner)
    assert not r.passed
    assert r.failure_mode in ("solar_deficit", "solar_energy_deficit")
