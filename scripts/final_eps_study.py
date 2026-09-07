#!/usr/bin/env python3
"""Milestone 4: integrated EPS robustness, margin rollup, and final
solar-array/battery sizing recommendation.

Reproduces the M1-M3 baseline (loads, array sizing, battery sizing) as
its sole source of truth, then:

  1. represents the M2/M3-selected hardware as a fixed EPSDesign;
  2. verifies it nominally (§6 pass/fail criteria);
  3. evaluates one deterministic "robust corner" scenario;
  4. finds it fails (solar deficit + DoD exceeded) and escalates only
     the capabilities shown to be inadequate, by the minimum practical
     increment, to a final design;
  5. re-verifies the final design against the robust corner;
  6. runs a 10,000-realization Monte Carlo robustness campaign against
     the *fixed* final design (never resizing hardware per draw);
  7. checks Monte Carlo convergence;
  8. ranks parameter sensitivity;
  9. builds a mission-operations feasibility map;
 10. builds a solar-array/battery hardware trade map;
 11. writes results/m4_final_eps_sizing.md and 5 figures.

Usage:
    python scripts/final_eps_study.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from power_budget.battery import BatteryConfig, simulate_orbit_soc, size_battery  # noqa: E402
from power_budget.budget import build_power_budget  # noqa: E402
from power_budget.integrated import (  # noqa: E402
    EPSDesign,
    compute_margins,
    eps_design_from_baseline,
    requirement_from_power_budget,
)
from power_budget.robustness import (  # noqa: E402
    convergence_study,
    evaluate_realization,
    evaluate_robust_corner,
    hardware_trade_map,
    mission_operations_map,
    nominal_params,
    robust_corner_params,
    run_monte_carlo,
    sensitivity_ranking,
)
from power_budget.solar import SolarArrayConfig, size_solar_array  # noqa: E402

from mission_baseline import BASELINE_SCHEDULE, ORBIT  # noqa: E402

RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"

SOLAR_CFG = SolarArrayConfig()
BATT_CFG = BatteryConfig()
SEED = 42
N_MC = 10000

# Final selected hardware (see §4/§20 below for the justification):
# the M2/M3 analytical-minimum design (0.0654 m^2 / 30 Wh) fails the
# deterministic robust corner (solar deficit + DoD exceeded); a
# minimal, quantitatively-derived escalation to 0.085 m^2 / 35 Wh
# closes it. See the "Escalation derivation" section printed below and
# docs/integrated_eps_methodology.md.
FINAL_ARRAY_AREA_M2 = 0.085
FINAL_BATTERY_CAPACITY_WH = 35.0


# ---------------------------------------------------------------------------
# Baseline reproduction + design construction
# ---------------------------------------------------------------------------
def compute_baseline_design() -> tuple[EPSDesign, EPSDesign]:
    """Return (M2/M3 analytical-minimum design, final escalated design)."""
    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    solar_result = size_solar_array(pb, SOLAR_CFG)
    battery_result = size_battery(pb, solar_result, BATT_CFG)
    minimum_design = eps_design_from_baseline(solar_result, battery_result)

    final_design = EPSDesign(
        array_area_m2=FINAL_ARRAY_AREA_M2,
        array_bol_density_w_m2=minimum_design.array_bol_density_w_m2,
        array_eol_density_w_m2=minimum_design.array_eol_density_w_m2,
        eta_sun_path=minimum_design.eta_sun_path,
        eta_recharge_path=minimum_design.eta_recharge_path,
        battery_capacity_bol_wh=FINAL_BATTERY_CAPACITY_WH,
        battery_f_cap_eol=minimum_design.battery_f_cap_eol,
        dod_max=minimum_design.dod_max,
        eta_discharge=minimum_design.eta_discharge,
    )
    return minimum_design, final_design


# ---------------------------------------------------------------------------
# Escalation derivation (§4/§20): find the minimum practical area/capacity
# ---------------------------------------------------------------------------
def derive_escalation(minimum_design: EPSDesign) -> pd.DataFrame:
    """Scan candidate (area, capacity) pairs against the robust corner to
    show the derivation of the final design honestly and reproducibly."""
    corner = robust_corner_params()
    areas = [minimum_design.array_area_m2, 0.075, 0.078, 0.08, 0.085, 0.09]
    caps = [minimum_design.battery_capacity_bol_wh, 30.0, 32.0, 32.5, 35.0, 40.0]
    rows = []
    for area in areas:
        for cap in caps:
            design = EPSDesign(
                array_area_m2=area,
                array_bol_density_w_m2=minimum_design.array_bol_density_w_m2,
                array_eol_density_w_m2=minimum_design.array_eol_density_w_m2,
                eta_sun_path=minimum_design.eta_sun_path,
                eta_recharge_path=minimum_design.eta_recharge_path,
                battery_capacity_bol_wh=cap,
                battery_f_cap_eol=minimum_design.battery_f_cap_eol,
                dod_max=minimum_design.dod_max,
                eta_discharge=minimum_design.eta_discharge,
            )
            r = evaluate_realization(design, corner)
            rows.append(
                {
                    "array_area_m2": area,
                    "battery_capacity_wh": cap,
                    "robust_corner_passes": r.passed,
                    "failure_mode": r.failure_mode,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    FIGURES_DIR.mkdir(exist_ok=True)

    pb = build_power_budget(BASELINE_SCHEDULE, ORBIT)
    minimum_design, final_design = compute_baseline_design()

    print("=== Milestone 4: Integrated EPS Robustness & Final Sizing ===\n")
    print(f"M2/M3 analytical-minimum design: area={minimum_design.array_area_m2:.4f} m^2, "
          f"battery={minimum_design.battery_capacity_bol_wh:.1f} Wh")
    print(f"Final selected design:           area={final_design.array_area_m2:.4f} m^2, "
          f"battery={final_design.battery_capacity_bol_wh:.1f} Wh\n")

    # --- nominal margins (both designs) ----------------------------------
    requirement = requirement_from_power_budget(pb)
    profile_min = simulate_orbit_soc(
        BASELINE_SCHEDULE, ORBIT, minimum_design.array_power_eol_w, SOLAR_CFG, BATT_CFG,
        minimum_design.battery_capacity_eol_j,
    )
    margins_min = compute_margins(minimum_design, requirement, profile_min.t_recharge_s)

    profile_final = simulate_orbit_soc(
        BASELINE_SCHEDULE, ORBIT, final_design.array_power_eol_w, SOLAR_CFG, BATT_CFG,
        final_design.battery_capacity_eol_j,
    )
    margins_final = compute_margins(final_design, requirement, profile_final.t_recharge_s)

    print("--- Nominal margins: M2/M3 minimum design ---")
    print(margins_min)
    print("--- Nominal margins: final selected design ---")
    print(margins_final)
    print()

    # --- robust corner -----------------------------------------------------
    corner_params = robust_corner_params()
    corner_min = evaluate_robust_corner(minimum_design)
    corner_final = evaluate_robust_corner(final_design)
    print(f"Robust corner params: {corner_params}")
    print(f"Robust corner vs. M2/M3 minimum design: passed={corner_min.passed}, "
          f"failure_mode={corner_min.failure_mode}")
    print(f"Robust corner vs. final design:         passed={corner_final.passed}, "
          f"failure_mode={corner_final.failure_mode}\n")

    escalation_df = derive_escalation(minimum_design)
    escalation_path = RESULTS_DIR / "m4_escalation_derivation.csv"
    escalation_df.to_csv(escalation_path, index=False)
    print(f"Wrote {escalation_path.relative_to(REPO_ROOT)}")

    # --- Monte Carlo campaign (fixed final design) --------------------------
    t0 = time.time()
    mc = run_monte_carlo(final_design, n=N_MC, seed=SEED)
    mc_time = time.time() - t0
    print(f"\nMonte Carlo (N={N_MC}, seed={SEED}, {mc_time:.2f}s):")
    print(f"  p_pass = {mc.p_pass*100:.2f}%  (95% CI: {mc.ci95[0]*100:.2f}%-{mc.ci95[1]*100:.2f}%)")
    print(f"  failure modes: {mc.failure_mode_counts}")
    mc.results_df.to_csv(RESULTS_DIR / "m4_monte_carlo_realizations.csv", index=False)
    print(f"Wrote {(RESULTS_DIR / 'm4_monte_carlo_realizations.csv').relative_to(REPO_ROOT)}")

    # --- convergence ---------------------------------------------------------
    conv_df = convergence_study(final_design, checkpoints=(100, 1000, 5000, 10000), seed=SEED)
    print("\n--- Monte Carlo convergence ---")
    print(conv_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    # --- sensitivity ranking ---------------------------------------------
    sens_df = sensitivity_ranking(final_design)
    print("\n--- Sensitivity ranking (final design) ---")
    print(sens_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    # --- mission-operations map ------------------------------------------
    # Range widened beyond the +/-1-sigma uncertainty bounds used
    # elsewhere so the map actually reveals the feasibility boundary
    # for this (quite robust) final design -- eclipse fraction 0.50 is
    # this package's physical upper bound (see UNCERTAINTY_PARAMS);
    # comms duty scale is pushed to 4.5x baseline to find the edge.
    eclipse_fracs = np.linspace(0.20, 0.50, 9)
    comms_scales = np.linspace(0.5, 4.5, 9)
    ops_df = mission_operations_map(final_design, eclipse_fracs, comms_scales)
    ops_df.to_csv(RESULTS_DIR / "m4_mission_operations_map.csv", index=False)
    print(f"\nWrote {(RESULTS_DIR / 'm4_mission_operations_map.csv').relative_to(REPO_ROOT)}")
    print(f"Mission-ops map feasibility counts:\n{ops_df['feasibility'].value_counts().to_string()}")

    # --- hardware trade map ------------------------------------------------
    area_grid = np.linspace(0.04, 0.11, 8)
    battery_grid = np.linspace(15.0, 45.0, 7)
    trade_nominal = hardware_trade_map(
        area_grid, battery_grid,
        minimum_design.array_eol_density_w_m2, minimum_design.array_bol_density_w_m2,
        minimum_design.eta_sun_path, minimum_design.eta_recharge_path,
        minimum_design.battery_f_cap_eol, minimum_design.dod_max, minimum_design.eta_discharge,
        scenario_params=nominal_params(),
    )
    trade_corner = hardware_trade_map(
        area_grid, battery_grid,
        minimum_design.array_eol_density_w_m2, minimum_design.array_bol_density_w_m2,
        minimum_design.eta_sun_path, minimum_design.eta_recharge_path,
        minimum_design.battery_f_cap_eol, minimum_design.dod_max, minimum_design.eta_discharge,
        scenario_params=corner_params,
    )
    trade_nominal.to_csv(RESULTS_DIR / "m4_hardware_trade_nominal.csv", index=False)
    trade_corner.to_csv(RESULTS_DIR / "m4_hardware_trade_corner.csv", index=False)
    print(f"Wrote {(RESULTS_DIR / 'm4_hardware_trade_nominal.csv').relative_to(REPO_ROOT)}")
    print(f"Wrote {(RESULTS_DIR / 'm4_hardware_trade_corner.csv').relative_to(REPO_ROOT)}")

    # --- final table ----------------------------------------------------
    table_path = write_final_table(
        pb, requirement, minimum_design, final_design, margins_final, profile_final,
        corner_final, mc,
    )
    print(f"\nWrote {table_path.relative_to(REPO_ROOT)}")

    # --- figures ----------------------------------------------------------
    fig1_integrated_timeline(pb, profile_final, final_design, FIGURES_DIR / "m4_integrated_timeline.png")
    print(f"Wrote {(FIGURES_DIR / 'm4_integrated_timeline.png').relative_to(REPO_ROOT)}")

    fig2_monte_carlo(mc, final_design, FIGURES_DIR / "m4_monte_carlo.png")
    print(f"Wrote {(FIGURES_DIR / 'm4_monte_carlo.png').relative_to(REPO_ROOT)}")

    fig3_sensitivity(sens_df, FIGURES_DIR / "m4_sensitivity.png")
    print(f"Wrote {(FIGURES_DIR / 'm4_sensitivity.png').relative_to(REPO_ROOT)}")

    fig4_operating_envelope(ops_df, FIGURES_DIR / "m4_operating_envelope.png")
    print(f"Wrote {(FIGURES_DIR / 'm4_operating_envelope.png').relative_to(REPO_ROOT)}")

    fig5_hardware_trade(
        trade_nominal, trade_corner, minimum_design, final_design,
        FIGURES_DIR / "m4_hardware_trade.png",
    )
    print(f"Wrote {(FIGURES_DIR / 'm4_hardware_trade.png').relative_to(REPO_ROOT)}")

    # --- headline numbers -------------------------------------------------
    print("\n=== Headline numbers ===")
    print(f"Final array area:               {final_design.array_area_m2:.4f} m^2")
    print(f"Final EOL array output:         {final_design.array_power_eol_w:.2f} W")
    print(f"Final battery BOL capacity:      {final_design.battery_capacity_bol_wh:.1f} Wh")
    print(f"Final battery EOL capacity:      {final_design.battery_capacity_eol_wh:.2f} Wh")
    print(f"Nominal solar energy margin:     {margins_final.solar_energy_margin:.3f}x")
    print(f"Nominal battery energy margin:   {margins_final.battery_energy_margin:.3f}x")
    print(f"Nominal recharge-time margin:    {margins_final.recharge_time_margin:.3f}x")
    print(f"Robust corner (final):          passed={corner_final.passed}")
    print(f"Monte Carlo closure probability: {mc.p_pass*100:.2f}% (95% CI "
          f"{mc.ci95[0]*100:.2f}-{mc.ci95[1]*100:.2f}%)")
    if mc.failure_mode_counts:
        dominant = max(mc.failure_mode_counts, key=mc.failure_mode_counts.get)
        n_failures = N_MC - mc.n_pass
        caveat = " (too few failures to establish a statistically dominant mode)" if n_failures < 10 else ""
        print(f"Observed failure mode(s):        {dominant} ({mc.failure_mode_counts[dominant]} of "
              f"{n_failures} failures){caveat}")


def write_final_table(pb, requirement, minimum_design, final_design, margins, profile, corner, mc) -> Path:
    lines = []
    lines.append("# Milestone 4 — Final Integrated EPS Sizing\n")
    lines.append(
        "Baseline 3U-cubesat-class LEO mission, reusing the Milestone 1-3 load, "
        "solar, and battery models unchanged. Final hardware selected after "
        "deterministic robust-corner and Monte Carlo robustness evaluation.\n"
    )
    lines.append("## Final EPS sizing table\n")
    lines.append("| Quantity | Requirement | Selected capability | Margin/status |")
    lines.append("|---|---:|---:|---:|")
    lines.append(
        f"| Peak load | {requirement.peak_load_w:.2f} W | "
        f"{final_design.array_power_eol_w:.2f} W (array EOL) | "
        f"{final_design.array_power_eol_w/requirement.peak_load_w:.2f}x |"
    )
    lines.append(
        f"| Orbit energy | {requirement.orbit_energy_j/3600:.2f} Wh | — | closes (M1/M2) |"
    )
    withdrawal_wh = requirement.e_eclipse_j / final_design.eta_discharge / 3600
    lines.append(
        f"| Eclipse battery withdrawal | {withdrawal_wh:.2f} Wh | "
        f"{final_design.battery_usable_energy_eol_j/3600:.2f} Wh (usable @ DoD_max, EOL) | "
        f"{margins.battery_energy_margin:.2f}x |"
    )
    lines.append(
        f"| Array area | {minimum_design.array_area_m2:.4f} m² (M2 analytical min) | "
        f"{final_design.array_area_m2:.4f} m² (selected) | "
        f"+{(final_design.array_area_m2/minimum_design.array_area_m2-1)*100:.0f}% |"
    )
    lines.append(
        f"| EOL array output | {minimum_design.array_power_eol_w:.2f} W (min design) | "
        f"{final_design.array_power_eol_w:.2f} W | — |"
    )
    lines.append(
        f"| Battery BOL capacity | {minimum_design.battery_capacity_bol_wh:.1f} Wh (M3 selected min) | "
        f"{final_design.battery_capacity_bol_wh:.1f} Wh (selected) | "
        f"+{(final_design.battery_capacity_bol_wh/minimum_design.battery_capacity_bol_wh-1)*100:.0f}% |"
    )
    lines.append(
        f"| Battery EOL capacity | — | {final_design.battery_capacity_eol_wh:.2f} Wh | — |"
    )
    lines.append(f"| Max DoD | {final_design.dod_max:.2f} | {1-profile.min_soc:.3f} (nominal actual) | pass |")
    lines.append(
        f"| Recharge time | {profile.t_recharge_s/60:.1f} min | "
        f"{profile.t_recharge_s/60:.1f} min of {requirement.t_sun_s/60:.1f} min sunlight | "
        f"{margins.recharge_time_margin:.2f}x |"
    )
    lines.append(f"| Monte Carlo closure | — | {mc.p_pass*100:.2f}% | 95% CI [{mc.ci95[0]*100:.2f}%, {mc.ci95[1]*100:.2f}%] |")
    lines.append(f"| Robust corner | — | {'PASS' if corner.passed else 'FAIL'} | — |")
    lines.append("")
    lines.append("## Nominal margins (final design)\n")
    lines.append(f"- Solar (recharge closure) margin: **{margins.solar_energy_margin:.3f}x**")
    lines.append(f"- Array power margin: **{margins.array_power_margin:.3f}x**")
    lines.append(f"- Battery energy margin: **{margins.battery_energy_margin:.3f}x**")
    lines.append(f"- Recharge-time margin: **{margins.recharge_time_margin:.3f}x**")
    lines.append("")
    text = "\n".join(lines) + "\n"
    path = RESULTS_DIR / "m4_final_eps_sizing.md"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def fig1_integrated_timeline(pb, profile, design, path: Path) -> None:
    from power_budget.energy import power_profile

    t_s, p_w = power_profile(BASELINE_SCHEDULE, dt_s=1.0)
    t_min = t_s / 60.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    ax1.plot(t_min, p_w, drawstyle="steps-post", color="#1f6f8b", linewidth=1.4, label="bus load")
    ax1.axhline(design.array_power_eol_w, color="#2e7d5b", linestyle="--", linewidth=1.2,
                label=f"array EOL output = {design.array_power_eol_w:.1f} W")
    ax1.axvspan(ORBIT.eclipse_start_s / 60, ORBIT.eclipse_end_s / 60, color="0.85", zorder=0)
    ax1.set_ylabel("Power [W]")
    ax1.set_title("Integrated nominal EPS timeline: load & generation, and battery SOC")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.3)

    t2_min = np.array(profile.t_s) / 60.0
    soc_pct = np.array(profile.soc) * 100.0
    ax2.plot(t2_min, soc_pct, marker="o", color="#7a1f2b", linewidth=1.8, markersize=4)
    ax2.axvspan(ORBIT.eclipse_start_s / 60, ORBIT.eclipse_end_s / 60, color="0.85", zorder=0, label="eclipse")
    ax2.axhline((1 - design.dod_max) * 100, color="#c1440e", linestyle="--", linewidth=1.2,
                label=f"DoD_max limit ({design.dod_max*100:.0f}%)")
    ax2.set_xlabel("Orbit elapsed time [min]")
    ax2.set_ylabel("Battery SOC [%]")
    ax2.set_ylim(0, 105)
    ax2.legend(loc="lower left", fontsize=8)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig2_monte_carlo(mc, design, path: Path) -> None:
    df = mc.results_df
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))

    ax = axes[0]
    ax.hist(df["recharge_margin"].dropna(), bins=40, color="#1f6f8b", edgecolor="white")
    ax.axvline(1.0, color="#c1440e", linestyle="--", label="closure limit (1.0x)")
    ax.set_xlabel("Recharge closure margin [-]")
    ax.set_ylabel("Realizations")
    ax.set_title("Solar recharge margin distribution")
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.hist(df["min_soc"].dropna() * 100, bins=40, color="#2e7d5b", edgecolor="white")
    ax.axvline((1 - design.dod_max) * 100, color="#c1440e", linestyle="--", label="DoD_max limit")
    ax.set_xlabel("Minimum SOC [%]")
    ax.set_title("Minimum-SOC distribution")
    ax.legend(fontsize=8)

    ax = axes[2]
    ax.hist(df["recharge_utilization"].dropna() * 100, bins=40, color="#7a1f2b", edgecolor="white")
    ax.axvline(100.0, color="#c1440e", linestyle="--", label="sunlight limit (100%)")
    ax.set_xlabel("Recharge utilization [% of sunlight]")
    ax.set_title("Recharge-time distribution")
    ax.legend(fontsize=8)

    fig.suptitle(
        f"Monte Carlo EPS robustness, N={mc.n:,}: closure = {mc.p_pass*100:.2f}% "
        f"(95% CI {mc.ci95[0]*100:.2f}-{mc.ci95[1]*100:.2f}%)", y=1.04
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


_LABELS = {
    "load_scale": "Spacecraft load level",
    "comms_duty_scale": "Communications duty",
    "payload_duty_scale": "Payload duty",
    "eclipse_fraction": "Eclipse fraction",
    "eta_cell": "PV cell efficiency",
    "f_array": "Array packing/incidence factor",
    "f_eol_pv": "Array EOL degradation",
    "eta_sun_path": "Sunlight power-path efficiency",
    "eta_recharge_path": "Battery charge-path efficiency",
    "eta_discharge": "Battery discharge-path efficiency",
    "f_cap_eol_batt": "Battery EOL capacity retention",
}


def fig3_sensitivity(sens_df: pd.DataFrame, path: Path) -> None:
    df = sens_df.copy()
    df["label"] = df["parameter"].map(_LABELS)
    df = df.sort_values("rank_score")

    fig, ax = plt.subplots(figsize=(8, 5.5))
    y = np.arange(len(df))
    ax.barh(y - 0.18, df["solar_margin_sensitivity"], height=0.35, color="#1f6f8b", label="Solar recharge margin")
    ax.barh(y + 0.18, df["dod_sensitivity"], height=0.35, color="#c1440e", label="Actual DoD")
    ax.set_yticks(y)
    ax.set_yticklabels(df["label"])
    ax.axvline(0.0, color="0.3", linewidth=0.8)
    ax.set_xlabel("Normalized sensitivity (fractional output change per +/-1 sigma)")
    ax.set_title("Parameter sensitivity ranking (final design)")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig4_operating_envelope(ops_df: pd.DataFrame, path: Path) -> None:
    pivot = ops_df.pivot(index="eclipse_fraction", columns="comms_duty_scale", values="feasibility")
    color_map = {"infeasible": 0, "marginal": 1, "feasible": 2}
    grid = pivot.replace(color_map).to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    cmap = matplotlib.colors.ListedColormap(["#c1440e", "#f2b134", "#2e7d5b"])
    im = ax.imshow(grid, aspect="auto", origin="lower", cmap=cmap, vmin=0, vmax=2,
                    extent=[pivot.columns.min(), pivot.columns.max(), pivot.index.min(), pivot.index.max()])
    ax.set_xlabel("Communications duty scale [x baseline]")
    ax.set_ylabel("Eclipse fraction [-]")
    ax.set_title("Mission operating envelope (fixed final EPS design)")
    ax.axhline(0.356, color="black", linestyle=":", linewidth=1, label="baseline eclipse fraction")
    ax.axvline(1.0, color="black", linestyle="--", linewidth=1, label="baseline comms duty")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    cbar = fig.colorbar(im, ax=ax, ticks=[0.33, 1.0, 1.67])
    cbar.ax.set_yticklabels(["infeasible", "marginal", "feasible"])
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig5_hardware_trade(trade_nominal, trade_corner, minimum_design, final_design, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))

    for ax, df, title in (
        (axes[0], trade_nominal, "Nominal conditions"),
        (axes[1], trade_corner, "Robust corner"),
    ):
        pivot = df.pivot(index="battery_capacity_wh", columns="array_area_m2", values="passed")
        grid = pivot.to_numpy(dtype=float)
        cmap = matplotlib.colors.ListedColormap(["#c1440e", "#2e7d5b"])
        ax.imshow(grid, aspect="auto", origin="lower", cmap=cmap, vmin=0, vmax=1,
                  extent=[pivot.columns.min(), pivot.columns.max(), pivot.index.min(), pivot.index.max()])
        ax.set_xlabel("Array area [m²]")
        ax.set_ylabel("Battery capacity [Wh]")
        ax.set_title(title)
        ax.scatter([minimum_design.array_area_m2], [minimum_design.battery_capacity_bol_wh],
                   marker="x", color="white", s=90, linewidths=2.5, label="M2/M3 analytical minimum")
        ax.scatter([final_design.array_area_m2], [final_design.battery_capacity_bol_wh],
                   marker="*", color="white", s=200, edgecolor="black", linewidths=0.8, label="Final selected")
        ax.legend(loc="lower right", fontsize=7.5, framealpha=0.9)

    fig.suptitle("Solar-array / battery hardware feasibility trade (green = pass, red = fail)", y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
