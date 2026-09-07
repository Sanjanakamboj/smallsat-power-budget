"""Regression / integration tests for the Milestone-2 script logic
(scripts/mission_baseline.build_schedule and
scripts/size_solar_array.py's sweep functions).

These import scripts/ as a path-inserted module, mirroring how the
scripts themselves do it, so the tests exercise the exact code path
run by ``python scripts/size_solar_array.py``.
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

import mission_baseline  # noqa: E402
import size_solar_array as m2  # noqa: E402


# ---------------------------------------------------------------------------
# M1 regression (must reproduce exactly, unchanged by M2 additions)
# ---------------------------------------------------------------------------


def test_m1_baseline_numbers_unchanged():
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    assert pb.orbit_average_power_w == pytest.approx(8.79, abs=5e-3)
    assert pb.peak_power_w == pytest.approx(14.50, abs=5e-3)
    assert pb.total_energy_j / 3600.0 == pytest.approx(13.85, abs=5e-3)
    assert pb.phase_energy["sunlight"].energy_j / 3600.0 == pytest.approx(9.47, abs=5e-3)
    assert pb.phase_energy["eclipse"].energy_j / 3600.0 == pytest.approx(4.38, abs=5e-3)


def test_build_schedule_defaults_match_frozen_baseline():
    generated = mission_baseline.build_schedule()
    frozen = mission_baseline.BASELINE_SCHEDULE
    assert len(generated.entries) == len(frozen.entries)
    for g, f in zip(generated.entries, frozen.entries):
        assert g.mode.name == f.mode.name
        assert g.start_s == pytest.approx(f.start_s)
        assert g.end_s == pytest.approx(f.end_s)


# ---------------------------------------------------------------------------
# build_schedule edge cases
# ---------------------------------------------------------------------------


def test_build_schedule_zero_payload_duration_collapses_cleanly():
    sched = mission_baseline.build_schedule(payload_duration_s=0.0)
    assert sched.total_duration_s() == pytest.approx(mission_baseline.ORBIT.period_s)
    names = {e.mode.name for e in sched.entries}
    assert "payload_imaging" not in names


def test_build_schedule_zero_downlink_duration_collapses_cleanly():
    sched = mission_baseline.build_schedule(downlink_duration_s=0.0)
    assert sched.total_duration_s() == pytest.approx(mission_baseline.ORBIT.period_s)
    names = {e.mode.name for e in sched.entries}
    assert "downlink" not in names


def test_build_schedule_rejects_overlapping_payload_and_downlink():
    with pytest.raises(ValueError):
        mission_baseline.build_schedule(payload_duration_s=1e6)


def test_build_schedule_rejects_downlink_exceeding_orbit():
    with pytest.raises(ValueError):
        mission_baseline.build_schedule(downlink_duration_s=1e6)


# ---------------------------------------------------------------------------
# Deterministic headline M2 script results
# ---------------------------------------------------------------------------


def test_m2_headline_numbers_deterministic():
    power_budget, result = m2.compute_baseline()
    assert result.t_sun_s / 60.0 == pytest.approx(60.92, abs=0.05)
    assert result.avg_power_w == pytest.approx(8.79, abs=5e-3)
    assert result.p_sa_raw_w == pytest.approx(15.44, abs=0.05)
    assert result.raw_to_avg_ratio == pytest.approx(1.76, abs=0.02)
    assert result.p_sa_design_w == pytest.approx(19.30, abs=0.05)
    assert result.bol_density_w_m2 == pytest.approx(347.055, abs=0.5)
    assert result.eol_density_w_m2 == pytest.approx(294.997, abs=0.5)
    assert result.area_m2 == pytest.approx(0.0654, abs=5e-4)
    assert result.closure.closes
    assert result.closure.margin_fraction == pytest.approx(0.25, rel=1e-6)


# ---------------------------------------------------------------------------
# Sweep sanity + monotonicity (mirrors what the script prints/plots)
# ---------------------------------------------------------------------------


def test_sweep_eclipse_fraction_monotonic_increasing():
    df = m2.sweep_eclipse_fraction()
    assert list(df["p_sa_raw_w"]) == sorted(df["p_sa_raw_w"])
    assert list(df["area_m2"]) == sorted(df["area_m2"])


def test_sweep_recharge_efficiency_monotonic_decreasing_area():
    df = m2.sweep_recharge_efficiency()
    # higher eta_recharge_path -> smaller area (better efficiency, less area needed)
    assert list(df["area_m2"]) == sorted(df["area_m2"], reverse=True)


def test_sweep_eol_degradation_inverse_scaling():
    df = m2.sweep_eol_degradation()
    ref = df.loc[df["f_eol"] == 1.0, "area_m2"].iloc[0]
    for _, row in df.iterrows():
        expected = ref / row["f_eol"]
        assert row["area_m2"] == pytest.approx(expected, rel=1e-9)


def test_sweep_cell_efficiency_inverse_scaling():
    df = m2.sweep_cell_efficiency()
    ref_eta, ref_area = df["eta_cell"].iloc[0], df["area_m2"].iloc[0]
    for _, row in df.iterrows():
        expected = ref_area * ref_eta / row["eta_cell"]
        assert row["area_m2"] == pytest.approx(expected, rel=1e-9)


def test_sweep_load_margin_linear_scaling():
    df = m2.sweep_load_margin()
    ref_power, ref_area = df["p_sa_design_w"].iloc[0], df["area_m2"].iloc[0]
    ref_sf = df["design_margin"].iloc[0]
    for _, row in df.iterrows():
        scale = row["design_margin"] / ref_sf
        assert row["p_sa_design_w"] == pytest.approx(ref_power * scale, rel=1e-9)
        assert row["area_m2"] == pytest.approx(ref_area * scale, rel=1e-9)


def test_sweep_downlink_duration_increases_area():
    df = m2.sweep_downlink_duration()
    assert list(df["area_m2"]) == sorted(df["area_m2"])


def test_sweep_payload_duration_increases_area():
    df = m2.sweep_payload_duration()
    assert list(df["area_m2"]) == sorted(df["area_m2"])


def test_payload_duty_is_stronger_area_driver_than_comms_duty():
    """Payload mode (14.5 W) draws more than downlink (10.2 W), so equal
    per-minute duty increases should move the array area more for
    payload than for downlink -- a central M2 operations-trade finding."""
    df_dl = m2.sweep_downlink_duration(durations_s=(0.0, 600.0))
    df_pl = m2.sweep_payload_duration(durations_s=(0.0, 600.0))
    delta_area_dl = df_dl["area_m2"].iloc[-1] - df_dl["area_m2"].iloc[0]
    delta_area_pl = df_pl["area_m2"].iloc[-1] - df_pl["area_m2"].iloc[0]
    assert delta_area_pl > delta_area_dl


# ---------------------------------------------------------------------------
# CFG used by the script must itself satisfy solar.SolarArrayConfig invariants
# ---------------------------------------------------------------------------


def test_script_default_config_is_valid_solar_array_config():
    cfg = m2.CFG
    assert isinstance(cfg, SolarArrayConfig)
    # re-run through size_solar_array to make sure it doesn't raise
    pb = build_power_budget(mission_baseline.BASELINE_SCHEDULE, mission_baseline.ORBIT)
    result = size_solar_array(pb, cfg)
    assert result.area_m2 > 0
