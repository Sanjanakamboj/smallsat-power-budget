#!/usr/bin/env python3
"""Milestone 3: battery sizing and eclipse energy storage.

Reuses the frozen Milestone-1 baseline mission and the Milestone-2
solar-array sizing as its sole sources of truth -- this script never
recreates the spacecraft load model or the array-sizing equations. It
only adds a battery/storage model on top of M1's ``E_eclipse`` and
M2's design array power / recharge-path efficiency.

Produces (under ``results/``):
  - m3_battery_sizing.md              headline battery sizing table (§21)
  - m3_eclipse_fraction_sweep.csv      eclipse-fraction sensitivity data
  - figures/m3_soc_profile.png         Figure 1: battery SOC over one orbit
  - figures/m3_dod_sensitivity.png     Figure 2: capacity vs. max DoD
  - figures/m3_eclipse_sensitivity.png Figure 3: capacity vs. eclipse fraction
  - figures/m3_timing_trade.png        Figure 4: activity-timing trade

Usage:
    python scripts/size_battery.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from power_budget.battery import BatteryConfig, size_battery  # noqa: E402
from power_budget.budget import build_power_budget  # noqa: E402
from power_budget.orbit import OrbitGeometry  # noqa: E402
from power_budget.schedule import OrbitSchedule, ScheduleEntry  # noqa: E402
from power_budget.solar import SolarArrayConfig, size_solar_array  # noqa: E402

from mission_baseline import (  # noqa: E402
    BASELINE_SCHEDULE,
    DOWNLINK,
    NOMINAL,
    ORBIT,
    build_schedule,
)

RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"

SOLAR_CFG = SolarArrayConfig()  # frozen M2 baseline assumptions
BATT_CFG = BatteryConfig()  # baseline M3 assumptions


# ---------------------------------------------------------------------------
# Baseline sizing
# ---------------------------------------------------------------------------
def compute_baseline():
    power_budget = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    solar_result = size_solar_array(power_budget, SOLAR_CFG)
    battery_result = size_battery(power_budget, solar_result, BATT_CFG)
    return power_budget, solar_result, battery_result


# ---------------------------------------------------------------------------
# Sensitivity sweeps
# ---------------------------------------------------------------------------
def _budget_for_eclipse_fraction(f_e: float):
    orbit = OrbitGeometry(period_s=ORBIT.period_s, eclipse_fraction=f_e)
    sched = OrbitSchedule(
        entries=(ScheduleEntry(NOMINAL, 0.0, ORBIT.period_s),),
        orbit_period_s=ORBIT.period_s,
    )
    return build_power_budget(sched, orbit)


def sweep_eclipse_fraction(fractions=(0.20, 0.30, 0.356, 0.40, 0.45)) -> pd.DataFrame:
    rows = []
    for f_e in fractions:
        pb = _budget_for_eclipse_fraction(f_e)
        solar_res = size_solar_array(pb, SOLAR_CFG)
        batt_res = size_battery(pb, solar_res, BATT_CFG)
        rows.append(
            {
                "eclipse_fraction": f_e,
                "eclipse_energy_wh": batt_res.e_eclipse_j / 3600.0,
                "raw_capacity_wh": batt_res.raw_capacity_j / 3600.0,
                "selected_capacity_wh": batt_res.selected_capacity_wh,
                "min_soc": batt_res.soc_profile.min_soc,
                "recharge_frac": (
                    batt_res.soc_profile.t_recharge_s / solar_res.t_sun_s
                    if batt_res.soc_profile.t_recharge_s is not None
                    else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def sweep_dod_max(dod_values=(0.15, 0.20, 0.25, 0.30, 0.40)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    solar_res = size_solar_array(pb, SOLAR_CFG)
    rows = []
    for dod in dod_values:
        cfg = BatteryConfig(dod_max=dod)
        res = size_battery(pb, solar_res, cfg)
        rows.append({"dod_max": dod, "raw_capacity_wh": res.raw_capacity_j / 3600.0})
    return pd.DataFrame(rows)


def sweep_discharge_efficiency(etas=(0.80, 0.85, 0.90, 0.95, 1.00)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    solar_res = size_solar_array(pb, SOLAR_CFG)
    rows = []
    for eta_d in etas:
        cfg = BatteryConfig(eta_discharge=eta_d)
        res = size_battery(pb, solar_res, cfg)
        rows.append({"eta_discharge": eta_d, "raw_capacity_wh": res.raw_capacity_j / 3600.0})
    return pd.DataFrame(rows)


def sweep_eol_retention(f_caps=(1.0, 0.9, 0.8, 0.7)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    solar_res = size_solar_array(pb, SOLAR_CFG)
    rows = []
    for f_cap in f_caps:
        cfg = BatteryConfig(f_cap_eol=f_cap)
        res = size_battery(pb, solar_res, cfg)
        rows.append({"f_cap_eol": f_cap, "bol_nameplate_wh": res.bol_nameplate_capacity_j / 3600.0})
    return pd.DataFrame(rows)


def sweep_capacity_margin(sfs=(1.0, 1.1, 1.2, 1.3)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    solar_res = size_solar_array(pb, SOLAR_CFG)
    rows = []
    for sf in sfs:
        cfg = BatteryConfig(capacity_margin=sf)
        res = size_battery(pb, solar_res, cfg)
        rows.append({"capacity_margin": sf, "design_capacity_eol_wh": res.design_capacity_eol_j / 3600.0})
    return pd.DataFrame(rows)


def sweep_downlink_duration(durations_s=(0.0, 300.0, 600.0, 900.0, 1200.0, 1500.0)) -> pd.DataFrame:
    """Downlink occurs in eclipse in the baseline schedule -- so its
    duration should drive battery capacity directly."""
    rows = []
    for d in durations_s:
        sched = build_schedule(downlink_duration_s=d)
        pb = build_power_budget(sched, ORBIT)
        solar_res = size_solar_array(pb, SOLAR_CFG)
        batt_res = size_battery(pb, solar_res, BATT_CFG)
        rows.append(
            {
                "downlink_duration_min": d / 60.0,
                "eclipse_energy_wh": pb.phase_energy["eclipse"].energy_j / 3600.0,
                "raw_capacity_wh": batt_res.raw_capacity_j / 3600.0,
            }
        )
    return pd.DataFrame(rows)


def sweep_payload_duration(durations_s=(0.0, 600.0, 1200.0, 1800.0, 2400.0)) -> pd.DataFrame:
    """Payload imaging occurs entirely in sunlight in the baseline schedule
    -- battery capacity should be comparatively insensitive to it."""
    rows = []
    for d in durations_s:
        sched = build_schedule(payload_duration_s=d)
        pb = build_power_budget(sched, ORBIT)
        solar_res = size_solar_array(pb, SOLAR_CFG)
        batt_res = size_battery(pb, solar_res, BATT_CFG)
        rows.append(
            {
                "payload_duration_min": d / 60.0,
                "eclipse_energy_wh": pb.phase_energy["eclipse"].energy_j / 3600.0,
                "raw_capacity_wh": batt_res.raw_capacity_j / 3600.0,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Activity-timing experiment (§20)
# ---------------------------------------------------------------------------
def _timing_schedule(downlink_start_s: float, downlink_duration_s: float = 600.0) -> OrbitSchedule:
    """NOMINAL everywhere except one DOWNLINK block, isolating the effect
    of *when* a fixed-duration, fixed-power activity occurs."""
    end_s = downlink_start_s + downlink_duration_s
    entries = (
        ScheduleEntry(NOMINAL, 0.0, downlink_start_s),
        ScheduleEntry(DOWNLINK, downlink_start_s, end_s),
        ScheduleEntry(NOMINAL, end_s, ORBIT.period_s),
    )
    return OrbitSchedule(entries=entries, orbit_period_s=ORBIT.period_s)


def run_timing_experiment(downlink_duration_s: float = 600.0) -> pd.DataFrame:
    sun_end = ORBIT.sunlight_end_s
    # placed well inside sunlight, and well inside eclipse
    sunlight_start = 1000.0
    eclipse_start = sun_end + 200.0
    assert sunlight_start + downlink_duration_s < sun_end
    assert eclipse_start + downlink_duration_s < ORBIT.period_s

    rows = []
    for label, start in (("sunlight", sunlight_start), ("eclipse", eclipse_start)):
        sched = _timing_schedule(start, downlink_duration_s)
        pb = build_power_budget(sched, ORBIT)
        solar_res = size_solar_array(pb, SOLAR_CFG)
        batt_res = size_battery(pb, solar_res, BATT_CFG)
        rows.append(
            {
                "placement": label,
                "orbit_avg_power_w": pb.orbit_average_power_w,
                "total_energy_wh": pb.total_energy_j / 3600.0,
                "eclipse_energy_wh": pb.phase_energy["eclipse"].energy_j / 3600.0,
                "p_sa_design_w": solar_res.p_sa_design_w,
                "raw_capacity_wh": batt_res.raw_capacity_j / 3600.0,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------
def write_sizing_table(battery_result) -> Path:
    r = battery_result
    p = r.soc_profile
    c = r.closure
    recharge_frac = (
        p.t_recharge_s / r.solar_result.t_sun_s if p.t_recharge_s is not None else float("nan")
    )

    lines = []
    lines.append("# Milestone 3 — Battery Sizing\n")
    lines.append(
        "Baseline 3U-cubesat-class LEO mission, reusing the Milestone-1 load "
        "model and Milestone-2 array sizing unchanged.\n"
    )
    lines.append("## Sizing table\n")
    lines.append("| Quantity | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Eclipse load energy | {r.e_eclipse_j/3600:.2f} Wh |")
    lines.append(f"| Discharge efficiency (eta_d) | {r.config.eta_discharge:.2f} |")
    lines.append(f"| Battery withdrawal | {r.withdrawal_j/3600:.2f} Wh |")
    lines.append(f"| Max DoD | {r.config.dod_max:.2f} |")
    lines.append(f"| Raw capacity | {r.raw_capacity_j/3600:.2f} Wh |")
    lines.append(f"| Capacity margin (SF_C) | {r.config.capacity_margin:.2f} |")
    lines.append(f"| EOL required capacity | {r.design_capacity_eol_j/3600:.2f} Wh |")
    lines.append(f"| EOL retention (f_cap,EOL) | {r.config.f_cap_eol:.2f} |")
    lines.append(f"| Minimum BOL nameplate | {r.bol_nameplate_capacity_j/3600:.2f} Wh |")
    lines.append(f"| Selected design capacity | {r.selected_capacity_wh:.1f} Wh |")
    lines.append(f"| Actual DoD at selected capacity | {r.actual_dod*100:.1f}% |")
    lines.append(f"| Baseline minimum SOC | {p.min_soc*100:.1f}% |")
    lines.append(
        f"| Recharge time / utilization | {p.t_recharge_s/60:.1f} min "
        f"({recharge_frac*100:.1f}% of sunlight) |"
    )
    lines.append("")
    lines.append("## Recharge closure (M2 <-> M3 consistency)\n")
    lines.append(
        f"Available sunlight recharge (via M2's eta_recharge_path): "
        f"**{c.available_recharge_j/3600:.2f} Wh**  \n"
        f"Required (battery-side withdrawal): **{c.required_j/3600:.2f} Wh**  \n"
        f"Margin: **{c.margin_fraction*100:.1f}%**  \n"
        f"Closes: **{c.closes}**\n"
    )
    text = "\n".join(lines) + "\n"
    path = RESULTS_DIR / "m3_battery_sizing.md"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def fig1_soc_profile(battery_result, orbit, path: Path) -> None:
    p = battery_result.soc_profile
    t_min = np.array(p.t_s) / 60.0
    soc_pct = np.array(p.soc) * 100.0

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(t_min, soc_pct, marker="o", color="#1f6f8b", linewidth=1.8, markersize=4)
    ax.axvspan(
        orbit.eclipse_start_s / 60.0, orbit.eclipse_end_s / 60.0, color="0.85", zorder=0, label="eclipse"
    )
    dod_limit_soc = (1.0 - battery_result.config.dod_max) * 100.0
    ax.axhline(
        dod_limit_soc, color="#c1440e", linestyle="--", linewidth=1.2,
        label=f"DoD_max limit = {battery_result.config.dod_max*100:.0f}% (SOC={dod_limit_soc:.0f}%)",
    )
    ax.axhline(
        p.min_soc * 100.0, color="#7a1f2b", linestyle=":", linewidth=1.2,
        label=f"baseline min SOC = {p.min_soc*100:.1f}%",
    )
    ax.set_xlabel("Orbit elapsed time [min]")
    ax.set_ylabel("State of charge [%]")
    ax.set_title(f"Baseline mission: battery SOC over one orbit ({battery_result.selected_capacity_wh:.0f} Wh selected)")
    ax.set_xlim(0, orbit.period_s / 60.0)
    ax.set_ylim(0, 105)
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig2_dod_sensitivity(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(df["dod_max"], df["raw_capacity_wh"], marker="o", color="#c1440e")
    ax.set_xlabel("Maximum allowable depth of discharge, DoD_max [-]")
    ax.set_ylabel("Raw required capacity [Wh]")
    ax.set_title("Required battery capacity vs. maximum DoD")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig3_eclipse_sensitivity(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(df["eclipse_fraction"], df["raw_capacity_wh"], marker="o", color="#2e7d5b")
    ax.set_xlabel("Eclipse fraction [-]")
    ax.set_ylabel("Raw required capacity [Wh]")
    ax.set_title("Required battery capacity vs. eclipse fraction")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig4_timing_trade(df: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))

    ax = axes[0]
    x = np.arange(len(df))
    ax.bar(x, df["total_energy_wh"], color="#1f6f8b", width=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(df["placement"])
    ax.set_ylabel("Total energy per orbit [Wh]")
    ax.set_title("Orbit energy (unchanged by timing)")
    ax.grid(True, axis="y", alpha=0.3)
    for xi, v in zip(x, df["total_energy_wh"]):
        ax.text(xi, v + 0.05, f"{v:.2f} Wh", ha="center", fontsize=9)
    span = df["total_energy_wh"].max() - df["total_energy_wh"].min()
    pad = max(span * 3, 0.3)
    ax.set_ylim(df["total_energy_wh"].min() - pad, df["total_energy_wh"].max() + pad)

    ax = axes[1]
    ax.bar(x, df["raw_capacity_wh"], color="#c1440e", width=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(df["placement"])
    ax.set_ylabel("Raw required battery capacity [Wh]")
    ax.set_title("Battery capacity (driven by timing)")
    ax.grid(True, axis="y", alpha=0.3)
    for xi, v in zip(x, df["raw_capacity_wh"]):
        ax.text(xi, v + 0.05, f"{v:.2f} Wh", ha="center", fontsize=9)

    fig.suptitle(
        "Same downlink activity, moved from sunlight to eclipse:\n"
        "orbit energy is unchanged, battery sizing is not", y=1.05
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    FIGURES_DIR.mkdir(exist_ok=True)

    power_budget, solar_result, battery_result = compute_baseline()

    print("=== Milestone 3: Battery Sizing (baseline mission) ===\n")
    print(battery_result.summary())
    print()

    table_path = write_sizing_table(battery_result)
    print(f"Wrote {table_path.relative_to(REPO_ROOT)}")

    # --- sensitivity sweeps -------------------------------------------
    df_eclipse = sweep_eclipse_fraction()
    df_dod = sweep_dod_max()
    df_eta_d = sweep_discharge_efficiency()
    df_retention = sweep_eol_retention()
    df_margin = sweep_capacity_margin()
    df_downlink = sweep_downlink_duration()
    df_payload = sweep_payload_duration()
    df_timing = run_timing_experiment()

    csv_path = RESULTS_DIR / "m3_eclipse_fraction_sweep.csv"
    df_eclipse.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path.relative_to(REPO_ROOT)}")

    print("\n--- Eclipse-fraction sweep ---")
    print(df_eclipse.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- DoD_max sweep ---")
    print(df_dod.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    ref = df_dod.iloc[0]
    for _, row in df_dod.iterrows():
        implied = ref["raw_capacity_wh"] * ref["dod_max"] / row["dod_max"]
        assert abs(implied - row["raw_capacity_wh"]) / row["raw_capacity_wh"] < 1e-9

    print("\n--- Discharge-efficiency sweep ---")
    print(df_eta_d.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- EOL-retention sweep ---")
    print(df_retention.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Capacity-margin sweep ---")
    print(df_margin.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Downlink (comms, in eclipse)-duration sweep ---")
    print(df_downlink.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Payload (imaging, in sunlight)-duration sweep ---")
    print(df_payload.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Activity-timing experiment (same downlink, sunlight vs. eclipse) ---")
    print(df_timing.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    # --- figures --------------------------------------------------------
    fig1_soc_profile(battery_result, power_budget.orbit, FIGURES_DIR / "m3_soc_profile.png")
    print(f"\nWrote {(FIGURES_DIR / 'm3_soc_profile.png').relative_to(REPO_ROOT)}")

    fig2_dod_sensitivity(df_dod, FIGURES_DIR / "m3_dod_sensitivity.png")
    print(f"Wrote {(FIGURES_DIR / 'm3_dod_sensitivity.png').relative_to(REPO_ROOT)}")

    fig3_eclipse_sensitivity(df_eclipse, FIGURES_DIR / "m3_eclipse_sensitivity.png")
    print(f"Wrote {(FIGURES_DIR / 'm3_eclipse_sensitivity.png').relative_to(REPO_ROOT)}")

    fig4_timing_trade(df_timing, FIGURES_DIR / "m3_timing_trade.png")
    print(f"Wrote {(FIGURES_DIR / 'm3_timing_trade.png').relative_to(REPO_ROOT)}")

    # --- headline numbers -------------------------------------------
    print("\n=== Headline numbers ===")
    print(f"Eclipse load energy:           {battery_result.e_eclipse_j/3600:.2f} Wh")
    print(f"Battery withdrawal:             {battery_result.withdrawal_j/3600:.2f} Wh")
    print(f"Raw capacity (DoD_max={BATT_CFG.dod_max:.2f}):  {battery_result.raw_capacity_j/3600:.2f} Wh")
    print(f"EOL required capacity:          {battery_result.design_capacity_eol_j/3600:.2f} Wh")
    print(f"Min BOL nameplate required:     {battery_result.bol_nameplate_capacity_j/3600:.2f} Wh")
    print(f"Selected design capacity:       {battery_result.selected_capacity_wh:.1f} Wh")
    print(f"Actual DoD at selected capacity:{battery_result.actual_dod*100:.1f}%")
    print(f"Minimum SOC over orbit:          {battery_result.soc_profile.min_soc*100:.1f}%")
    print(
        f"Recharge closure margin:        {battery_result.closure.margin_fraction*100:.1f}% "
        f"(closes={battery_result.closure.closes})"
    )
    recharge_frac = (
        battery_result.soc_profile.t_recharge_s / solar_result.t_sun_s
        if battery_result.soc_profile.t_recharge_s is not None
        else float("nan")
    )
    print(
        f"Recharge time:                  {battery_result.soc_profile.t_recharge_s/60:.1f} min "
        f"({recharge_frac*100:.1f}% of sunlight duration)"
    )


if __name__ == "__main__":
    main()
