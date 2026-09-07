#!/usr/bin/env python3
"""Milestone 2: solar-array sizing and sunlight-only energy closure.

Reuses the frozen Milestone-1 baseline mission (orbit, modes, schedule)
and the Milestone-1 :class:`~power_budget.budget.PowerBudget` (sunlight
/ eclipse energy) as its sole source of spacecraft-load truth. This
script never recreates the load model -- it only adds a solar/EPS
model on top of M1's ``E_sun`` / ``E_eclipse`` outputs.

Produces (under ``results/``):
  - m2_solar_array_sizing.md         headline sizing table (§20)
  - m2_eclipse_fraction_sweep.csv    eclipse-fraction sensitivity data
  - figures/m2_energy_flow.png       Figure 1: orbital energy flow
  - figures/m2_eclipse_sensitivity.png  Figure 2: power/area vs eclipse fraction
  - figures/m2_area_sensitivity.png  Figure 3: cell/EOL/recharge sensitivities
  - figures/m2_ops_trade.png         Figure 4: array area vs comms/payload duty

Usage:
    python scripts/size_solar_array.py
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

from power_budget.budget import build_power_budget  # noqa: E402
from power_budget.modes import Mode  # noqa: E402
from power_budget.orbit import OrbitGeometry  # noqa: E402
from power_budget.schedule import OrbitSchedule, ScheduleEntry  # noqa: E402
from power_budget.solar import (  # noqa: E402
    SolarArrayConfig,
    bol_power_density_w_m2,
    eol_power_density_w_m2,
    required_array_area_m2,
    required_array_power_design_w,
    required_array_power_raw_w,
    size_solar_array,
)

from mission_baseline import (  # noqa: E402
    BASELINE_SCHEDULE,
    NOMINAL,
    ORBIT,
    build_schedule,
)

RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"

CFG = SolarArrayConfig()  # baseline representative EPS/array assumptions


# ---------------------------------------------------------------------------
# Baseline sizing
# ---------------------------------------------------------------------------
def compute_baseline():
    power_budget = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    result = size_solar_array(power_budget, CFG)
    return power_budget, result


# ---------------------------------------------------------------------------
# Sensitivity sweeps
# ---------------------------------------------------------------------------
def _budget_for_eclipse_fraction(f_e: float) -> "PowerBudget":
    """Single-mode (nominal-only) orbit at eclipse fraction f_e, holding
    the orbit period and mode power fixed -- isolates the effect of
    eclipse fraction alone on array sizing."""
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
        res = size_solar_array(pb, CFG)
        rows.append(
            {
                "eclipse_fraction": f_e,
                "sunlight_duration_min": res.t_sun_s / 60.0,
                "eclipse_energy_wh": res.e_eclipse_j / 3600.0,
                "p_sa_raw_w": res.p_sa_raw_w,
                "p_sa_design_w": res.p_sa_design_w,
                "area_m2": res.area_m2,
            }
        )
    return pd.DataFrame(rows)


def sweep_recharge_efficiency(etas=(0.60, 0.70, 0.80, 0.85, 0.90, 0.95)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    rows = []
    for eta_c in etas:
        cfg = SolarArrayConfig(eta_recharge_path=eta_c)
        res = size_solar_array(pb, cfg)
        rows.append(
            {"eta_recharge_path": eta_c, "p_sa_raw_w": res.p_sa_raw_w, "area_m2": res.area_m2}
        )
    return pd.DataFrame(rows)


def sweep_eol_degradation(f_eols=(1.0, 0.9, 0.8, 0.7)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    rows = []
    for f_eol in f_eols:
        cfg = SolarArrayConfig(f_eol=f_eol)
        res = size_solar_array(pb, cfg)
        rows.append({"f_eol": f_eol, "area_m2": res.area_m2})
    return pd.DataFrame(rows)


def sweep_cell_efficiency(etas=(0.15, 0.20, 0.25, 0.30, 0.35)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    rows = []
    for eta_cell in etas:
        cfg = SolarArrayConfig(eta_cell=eta_cell)
        res = size_solar_array(pb, cfg)
        rows.append({"eta_cell": eta_cell, "area_m2": res.area_m2})
    return pd.DataFrame(rows)


def sweep_load_margin(sfs=(1.0, 1.1, 1.2, 1.3)) -> pd.DataFrame:
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    rows = []
    for sf in sfs:
        cfg = SolarArrayConfig(design_margin=sf)
        res = size_solar_array(pb, cfg)
        rows.append(
            {"design_margin": sf, "p_sa_design_w": res.p_sa_design_w, "area_m2": res.area_m2}
        )
    return pd.DataFrame(rows)


def sweep_downlink_duration(durations_s=(0.0, 300.0, 600.0, 900.0, 1200.0, 1500.0)) -> pd.DataFrame:
    rows = []
    for d in durations_s:
        sched = build_schedule(downlink_duration_s=d)
        pb = build_power_budget(sched, ORBIT)
        res = size_solar_array(pb, CFG)
        rows.append(
            {
                "downlink_duration_min": d / 60.0,
                "total_energy_wh": pb.total_energy_j / 3600.0,
                "p_sa_design_w": res.p_sa_design_w,
                "area_m2": res.area_m2,
            }
        )
    return pd.DataFrame(rows)


def sweep_payload_duration(durations_s=(0.0, 600.0, 1200.0, 1800.0, 2400.0)) -> pd.DataFrame:
    rows = []
    for d in durations_s:
        sched = build_schedule(payload_duration_s=d)
        pb = build_power_budget(sched, ORBIT)
        res = size_solar_array(pb, CFG)
        rows.append(
            {
                "payload_duration_min": d / 60.0,
                "total_energy_wh": pb.total_energy_j / 3600.0,
                "p_sa_design_w": res.p_sa_design_w,
                "area_m2": res.area_m2,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------
def write_sizing_table(power_budget, result) -> Path:
    sun = power_budget.phase_energy["sunlight"]
    ecl = power_budget.phase_energy["eclipse"]
    required_recharge_j = (
        result.e_sun_j / CFG.eta_sun_path + result.e_eclipse_j / CFG.eta_recharge_path
    )

    lines = []
    lines.append("# Milestone 2 — Solar Array Sizing\n")
    lines.append(
        "Baseline 3U-cubesat-class LEO mission, reusing the Milestone-1 "
        "load model unchanged. All quantities in SI unless labeled.\n"
    )
    lines.append("## Sizing table\n")
    lines.append("| Quantity | Raw | Design/EOL |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| Sunlight duration | {result.t_sun_s/60:.1f} min | {result.t_sun_s/60:.1f} min |"
    )
    lines.append(
        f"| Sunlight load energy | {sun.energy_wh:.2f} Wh | — |"
    )
    lines.append(
        f"| Eclipse load energy | {ecl.energy_wh:.2f} Wh | — |"
    )
    lines.append(
        f"| Required recharge energy (raw-equiv.) | {required_recharge_j/3600:.2f} Wh | — |"
    )
    lines.append(
        f"| Required array output | {result.p_sa_raw_w:.2f} W | {result.p_sa_design_w:.2f} W |"
    )
    lines.append(
        f"| Usable array power density | {result.bol_density_w_m2:.1f} W/m² (BOL) | "
        f"{result.eol_density_w_m2:.1f} W/m² (EOL) |"
    )
    lines.append(
        f"| Required area | — | {result.area_m2:.3f} m² |"
    )
    lines.append(
        f"| Naive avg-power estimate | {result.avg_power_w:.2f} W | — |"
    )
    lines.append(
        f"| Raw / naive-avg ratio | {result.raw_to_avg_ratio:.2f}x | — |"
    )
    lines.append("")
    lines.append("## Assumed efficiency / degradation factors\n")
    lines.append("| Factor | Value | Meaning |")
    lines.append("|---|---:|---|")
    lines.append(f"| S0 (solar constant) | {CFG.s0_w_m2:.0f} W/m² | representative, fixed, 1 AU |")
    lines.append(f"| eta_cell (BOL PV efficiency) | {CFG.eta_cell:.2f} | representative multi-junction cell |")
    lines.append(f"| f_array (incidence/packing/utilization) | {CFG.f_array:.2f} | single lumped derating factor |")
    lines.append(f"| f_EOL (end-of-life degradation) | {CFG.f_eol:.2f} | radiation + thermal-cycling loss |")
    lines.append(f"| eta_sun_path (array-to-sunlight-load path) | {CFG.eta_sun_path:.2f} | regulation + harness |")
    lines.append(f"| eta_recharge_path (eclipse recharge path) | {CFG.eta_recharge_path:.2f} | battery charge-conversion |")
    lines.append(f"| SF_P (design margin) | {CFG.design_margin:.2f} | 25% design/load-growth margin |")
    lines.append("")
    lines.append("## Energy closure\n")
    c = result.closure
    lines.append(
        f"Generated (design power x sunlight duration): **{c.generated_j/3600:.2f} Wh**  \n"
        f"Required (raw-equivalent, unity margin): **{c.required_raw_j/3600:.2f} Wh**  \n"
        f"Residual margin: **{c.margin_fraction*100:.1f}%**  \n"
        f"Closes: **{c.closes}**\n"
    )
    text = "\n".join(lines) + "\n"
    path = RESULTS_DIR / "m2_solar_array_sizing.md"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def fig1_energy_flow(power_budget, result, path: Path) -> None:
    """Figure 1: orbital energy flow -- sunlight load, eclipse recharge
    (raw-equivalent), and margin, stacked as an energy bar."""
    sun_wh = result.e_sun_j / CFG.eta_sun_path / 3600.0
    recharge_wh = result.e_eclipse_j / CFG.eta_recharge_path / 3600.0
    raw_total_wh = sun_wh + recharge_wh
    design_total_wh = result.p_sa_design_w * result.t_sun_s / 3600.0
    margin_wh = design_total_wh - raw_total_wh

    fig, ax = plt.subplots(figsize=(6.5, 4.8))
    labels = ["Required\n(raw)", "Generated\n(design)"]
    x = np.arange(len(labels))

    sun_vals = [sun_wh, sun_wh]
    recharge_vals = [recharge_wh, recharge_wh]
    margin_vals = [0.0, margin_wh]

    ax.bar(x, sun_vals, color="#f2b134", label="Sunlight-load energy (raw-equiv.)")
    ax.bar(x, recharge_vals, bottom=sun_vals, color="#1f6f8b", label="Eclipse-recharge energy (raw-equiv.)")
    bottoms = [s + r for s, r in zip(sun_vals, recharge_vals)]
    ax.bar(x, margin_vals, bottom=bottoms, color="#8fbf8f", label="Design margin")

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Array raw electrical energy per orbit [Wh]")
    ax.set_title("Baseline mission: orbital energy flow (array output side)")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax.grid(True, axis="y", alpha=0.3)
    for xi, tot in zip(x, [raw_total_wh, design_total_wh]):
        ax.text(xi, tot + 0.2, f"{tot:.2f} Wh", ha="center", fontsize=9)
    ax.set_ylim(0, design_total_wh * 1.2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig2_eclipse_sensitivity(df: pd.DataFrame, path: Path) -> None:
    """Figure 2: required array power/area vs. eclipse fraction."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))

    ax1.plot(df["eclipse_fraction"], df["p_sa_design_w"], marker="o", color="#c1440e")
    ax1.set_xlabel("Eclipse fraction [-]")
    ax1.set_ylabel("Design array power [W]")
    ax1.set_title("Required array power vs. eclipse fraction")
    ax1.grid(True, alpha=0.3)

    ax2.plot(df["eclipse_fraction"], df["area_m2"], marker="o", color="#2e7d5b")
    ax2.set_xlabel("Eclipse fraction [-]")
    ax2.set_ylabel("Required array area [m²]")
    ax2.set_title("Required array area vs. eclipse fraction")
    ax2.grid(True, alpha=0.3)

    fig.suptitle("Sunlight-time penalty: less sunlight -> larger array", y=1.03)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig3_area_sensitivity(df_eta_c, df_eol, df_cell, path: Path) -> None:
    """Figure 3: array-area sensitivity to recharge efficiency, EOL
    degradation, and cell efficiency (three small panels)."""
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.0))

    ax = axes[0]
    ax.plot(df_eta_c["eta_recharge_path"], df_eta_c["area_m2"], marker="o", color="#1f6f8b")
    ax.set_xlabel("Recharge-path efficiency, η_c [-]")
    ax.set_ylabel("Required area [m²]")
    ax.set_title("vs. recharge efficiency")
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(df_eol["f_eol"], df_eol["area_m2"], marker="o", color="#c1440e")
    ax.set_xlabel("EOL degradation factor, f_EOL [-]")
    ax.set_title("vs. EOL degradation")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.plot(df_cell["eta_cell"], df_cell["area_m2"], marker="o", color="#7a1f2b")
    ax.set_xlabel("Cell efficiency, η_cell [-]")
    ax.set_title("vs. cell efficiency")
    ax.grid(True, alpha=0.3)

    fig.suptitle("Array-area sensitivity to EPS/technology assumptions", y=1.04)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig4_ops_trade(df_downlink, df_payload, path: Path) -> None:
    """Figure 4: array area vs. communications duty and payload duty."""
    fig, ax = plt.subplots(figsize=(7.5, 4.8))

    ax.plot(
        df_downlink["downlink_duration_min"],
        df_downlink["area_m2"],
        marker="o",
        color="#1f6f8b",
        label="vs. downlink (comms) duration",
    )
    ax.plot(
        df_payload["payload_duration_min"],
        df_payload["area_m2"],
        marker="s",
        color="#c1440e",
        label="vs. payload-imaging duration",
    )
    ax.set_xlabel("Mode duration per orbit [min]")
    ax.set_ylabel("Required array area [m²]")
    ax.set_title("Mission-operations trade: array area vs. duty cycle")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    FIGURES_DIR.mkdir(exist_ok=True)

    power_budget, result = compute_baseline()

    print("=== Milestone 2: Solar Array Sizing (baseline mission) ===\n")
    print(result.summary())
    print()

    table_path = write_sizing_table(power_budget, result)
    print(f"Wrote {table_path.relative_to(REPO_ROOT)}")

    # --- sensitivity sweeps -------------------------------------------
    df_eclipse = sweep_eclipse_fraction()
    df_eta_c = sweep_recharge_efficiency()
    df_eol = sweep_eol_degradation()
    df_cell = sweep_cell_efficiency()
    df_margin = sweep_load_margin()
    df_downlink = sweep_downlink_duration()
    df_payload = sweep_payload_duration()

    csv_path = RESULTS_DIR / "m2_eclipse_fraction_sweep.csv"
    df_eclipse.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path.relative_to(REPO_ROOT)}")

    print("\n--- Eclipse-fraction sweep ---")
    print(df_eclipse.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Recharge-efficiency sweep ---")
    print(df_eta_c.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- EOL-degradation sweep ---")
    print(df_eol.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    ratio = df_eol["area_m2"].iloc[0] * df_eol["f_eol"].iloc[0]
    for _, row in df_eol.iterrows():
        implied = ratio / row["f_eol"]
        assert abs(implied - row["area_m2"]) / row["area_m2"] < 1e-9

    print("\n--- Cell-efficiency sweep ---")
    print(df_cell.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Load-margin sweep ---")
    print(df_margin.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Downlink (comms)-duration sweep ---")
    print(df_downlink.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\n--- Payload-duration sweep ---")
    print(df_payload.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    # --- figures --------------------------------------------------------
    fig1_energy_flow(power_budget, result, FIGURES_DIR / "m2_energy_flow.png")
    print(f"\nWrote {(FIGURES_DIR / 'm2_energy_flow.png').relative_to(REPO_ROOT)}")

    fig2_eclipse_sensitivity(df_eclipse, FIGURES_DIR / "m2_eclipse_sensitivity.png")
    print(f"Wrote {(FIGURES_DIR / 'm2_eclipse_sensitivity.png').relative_to(REPO_ROOT)}")

    fig3_area_sensitivity(
        df_eta_c, df_eol, df_cell, FIGURES_DIR / "m2_area_sensitivity.png"
    )
    print(f"Wrote {(FIGURES_DIR / 'm2_area_sensitivity.png').relative_to(REPO_ROOT)}")

    fig4_ops_trade(df_downlink, df_payload, FIGURES_DIR / "m2_ops_trade.png")
    print(f"Wrote {(FIGURES_DIR / 'm2_ops_trade.png').relative_to(REPO_ROOT)}")

    # --- headline numbers -------------------------------------------
    print("\n=== Headline numbers ===")
    print(f"Sunlight duration:            {result.t_sun_s/60:.2f} min")
    print(f"Naive avg power (P_avg):      {result.avg_power_w:.2f} W")
    print(f"Raw required array power:     {result.p_sa_raw_w:.2f} W  ({result.raw_to_avg_ratio:.2f}x P_avg)")
    print(f"Design array power:           {result.p_sa_design_w:.2f} W")
    print(f"BOL usable power density:     {result.bol_density_w_m2:.1f} W/m^2")
    print(f"EOL usable power density:     {result.eol_density_w_m2:.1f} W/m^2")
    print(f"Required array area:          {result.area_m2:.4f} m^2")
    print(
        f"Energy closure margin:        {result.closure.margin_fraction*100:.1f}% "
        f"(closes={result.closure.closes})"
    )


if __name__ == "__main__":
    main()
