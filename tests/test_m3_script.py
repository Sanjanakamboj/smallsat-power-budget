"""Regression / integration tests for the Milestone-3 script logic
(scripts/size_battery.py's sweeps and the activity-timing experiment).

Mirrors tests/test_m2_script.py's approach: import scripts/ as a
path-inserted module so tests exercise the exact code path run by
``python scripts/size_battery.py``.
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
from power_budget.solar import SolarArrayConfig, size_solar_array  # noqa: E402
from power_budget.battery import BatteryConfig, size_battery  # noqa: E402

import mission_baseline  # noqa: E402
import size_battery as m3  # noqa: E402


# ---------------------------------------------------------------------------
# M1/M2 regression (must reproduce exactly, unchanged by M3 additions)
# ---------------------------------------------------------------------------


def test_m1_baseline_numbers_unchanged():
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    assert pb.orbit_average_power_w == pytest.approx(8.79, abs=5e-3)
    assert pb.peak_power_w == pytest.approx(14.50, abs=5e-3)
    assert pb.phase_energy["sunlight"].energy_j / 3600.0 == pytest.approx(9.47, abs=5e-3)
    assert pb.phase_energy["eclipse"].energy_j / 3600.0 == pytest.approx(4.38, abs=5e-3)


def test_m2_baseline_numbers_unchanged():
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    assert solar_result.p_sa_raw_w == pytest.approx(15.44, abs=0.05)
    assert solar_result.p_sa_design_w == pytest.approx(19.30, abs=0.05)
    assert solar_result.area_m2 == pytest.approx(0.0654, abs=5e-4)


# ---------------------------------------------------------------------------
# Deterministic headline M3 script results
# ---------------------------------------------------------------------------


def test_m3_headline_numbers_deterministic():
    power_budget, solar_result, battery_result = m3.compute_baseline()
    assert battery_result.e_eclipse_j / 3600.0 == pytest.approx(4.38, abs=5e-3)
    assert battery_result.withdrawal_j / 3600.0 == pytest.approx(4.61, abs=0.02)
    assert battery_result.raw_capacity_j / 3600.0 == pytest.approx(18.46, abs=0.05)
    assert battery_result.design_capacity_eol_j / 3600.0 == pytest.approx(23.07, abs=0.05)
    assert battery_result.bol_nameplate_capacity_j / 3600.0 == pytest.approx(28.84, abs=0.05)
    assert battery_result.selected_capacity_wh == pytest.approx(30.0, abs=1e-6)
    assert battery_result.actual_dod == pytest.approx(0.154, abs=0.002)
    assert battery_result.soc_profile.min_soc == pytest.approx(0.846, abs=0.002)
    assert battery_result.closure.closes
    assert battery_result.closure.margin_fraction == pytest.approx(0.672, abs=0.01)
    assert battery_result.soc_profile.t_recharge_s / 60.0 == pytest.approx(42.3, abs=0.5)


# ---------------------------------------------------------------------------
# Sweep sanity + monotonicity
# ---------------------------------------------------------------------------


def test_sweep_eclipse_fraction_monotonic_increasing_capacity():
    df = m3.sweep_eclipse_fraction()
    assert list(df["raw_capacity_wh"]) == sorted(df["raw_capacity_wh"])
    assert all(b > a for a, b in zip(df["raw_capacity_wh"], df["raw_capacity_wh"][1:]))


def test_sweep_dod_max_inverse_scaling():
    df = m3.sweep_dod_max()
    ref = df.loc[df["dod_max"] == 0.25].iloc[0]
    for _, row in df.iterrows():
        expected = ref["raw_capacity_wh"] * 0.25 / row["dod_max"]
        assert row["raw_capacity_wh"] == pytest.approx(expected, rel=1e-9)


def test_sweep_discharge_efficiency_inverse_scaling():
    df = m3.sweep_discharge_efficiency()
    ref = df.loc[df["eta_discharge"] == 1.0].iloc[0]
    for _, row in df.iterrows():
        expected = ref["raw_capacity_wh"] * 1.0 / row["eta_discharge"]
        assert row["raw_capacity_wh"] == pytest.approx(expected, rel=1e-9)
    # monotonic decreasing as efficiency improves
    assert list(df["raw_capacity_wh"]) == sorted(df["raw_capacity_wh"], reverse=True)


def test_sweep_eol_retention_inverse_scaling():
    df = m3.sweep_eol_retention()
    ref = df.loc[df["f_cap_eol"] == 1.0].iloc[0]
    for _, row in df.iterrows():
        expected = ref["bol_nameplate_wh"] * 1.0 / row["f_cap_eol"]
        assert row["bol_nameplate_wh"] == pytest.approx(expected, rel=1e-9)


def test_sweep_capacity_margin_linear_scaling():
    df = m3.sweep_capacity_margin()
    ref = df.iloc[0]
    for _, row in df.iterrows():
        scale = row["capacity_margin"] / ref["capacity_margin"]
        assert row["design_capacity_eol_wh"] == pytest.approx(
            ref["design_capacity_eol_wh"] * scale, rel=1e-9
        )


def test_sweep_downlink_duration_increases_capacity():
    """Downlink occurs in eclipse in the baseline -> capacity must rise."""
    df = m3.sweep_downlink_duration()
    assert list(df["raw_capacity_wh"]) == sorted(df["raw_capacity_wh"])
    assert df["raw_capacity_wh"].iloc[-1] > df["raw_capacity_wh"].iloc[0]


def test_sweep_payload_duration_leaves_capacity_unchanged():
    """Payload occurs entirely in sunlight in the baseline -> battery
    capacity should be insensitive even though array area is not."""
    df = m3.sweep_payload_duration()
    assert df["raw_capacity_wh"].max() - df["raw_capacity_wh"].min() < 1e-6
    assert df["eclipse_energy_wh"].max() - df["eclipse_energy_wh"].min() < 1e-6


def test_payload_duty_affects_capacity_far_less_than_comms_duty():
    df_dl = m3.sweep_downlink_duration(durations_s=(0.0, 600.0))
    df_pl = m3.sweep_payload_duration(durations_s=(0.0, 600.0))
    delta_dl = df_dl["raw_capacity_wh"].iloc[-1] - df_dl["raw_capacity_wh"].iloc[0]
    delta_pl = df_pl["raw_capacity_wh"].iloc[-1] - df_pl["raw_capacity_wh"].iloc[0]
    assert delta_dl > 0
    assert delta_pl == pytest.approx(0.0, abs=1e-6)
    assert delta_dl > delta_pl


# ---------------------------------------------------------------------------
# Activity-timing experiment
# ---------------------------------------------------------------------------


def test_timing_experiment_orbit_energy_invariant():
    """Total orbit energy and orbit-average power must not depend on
    when (sunlight vs. eclipse) a fixed-duration, fixed-power activity
    occurs -- only battery/array sizing should change."""
    df = m3.run_timing_experiment()
    assert len(df) == 2
    total_energies = df["total_energy_wh"].to_numpy()
    avg_powers = df["orbit_avg_power_w"].to_numpy()
    assert total_energies[0] == pytest.approx(total_energies[1], rel=1e-9)
    assert avg_powers[0] == pytest.approx(avg_powers[1], rel=1e-9)


def test_timing_experiment_battery_capacity_changes():
    df = m3.run_timing_experiment()
    sunlight_row = df.loc[df["placement"] == "sunlight"].iloc[0]
    eclipse_row = df.loc[df["placement"] == "eclipse"].iloc[0]
    # moving the same activity into eclipse must not decrease required capacity
    assert eclipse_row["raw_capacity_wh"] > sunlight_row["raw_capacity_wh"]
    assert eclipse_row["eclipse_energy_wh"] > sunlight_row["eclipse_energy_wh"]


def test_timing_experiment_eclipse_energy_matches_placement():
    """Sanity check the experiment construction itself: eclipse-phase
    energy is NOMINAL everywhere except the 600 s downlink window, so
    moving that window into eclipse raises eclipse-phase energy by the
    *marginal* power difference (DOWNLINK - NOMINAL) over its duration
    -- NOMINAL was already running there in the sunlight-placement case,
    it is not replacing a zero-power gap."""
    df = m3.run_timing_experiment(downlink_duration_s=600.0)
    sunlight_row = df.loc[df["placement"] == "sunlight"].iloc[0]
    eclipse_row = df.loc[df["placement"] == "eclipse"].iloc[0]
    delta_eclipse_energy = eclipse_row["eclipse_energy_wh"] - sunlight_row["eclipse_energy_wh"]
    marginal_power_w = mission_baseline.DOWNLINK.power_w - mission_baseline.NOMINAL.power_w
    expected_delta_wh = marginal_power_w * 600.0 / 3600.0
    assert delta_eclipse_energy == pytest.approx(expected_delta_wh, rel=1e-6)


# ---------------------------------------------------------------------------
# CFG used by the script must be valid, and full pipeline must not raise
# ---------------------------------------------------------------------------


def test_script_default_configs_are_valid():
    assert isinstance(m3.SOLAR_CFG, SolarArrayConfig)
    assert isinstance(m3.BATT_CFG, BatteryConfig)
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    solar_result = size_solar_array(pb, m3.SOLAR_CFG)
    battery_result = size_battery(pb, solar_result, m3.BATT_CFG)
    assert battery_result.selected_capacity_wh > 0
