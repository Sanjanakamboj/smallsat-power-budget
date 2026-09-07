#!/usr/bin/env python3
"""Run the Milestone-1 power-budget analysis for the baseline mission.

Produces (under ``results/``):
  - power_budget_table.csv     per-mode power/energy/duty-cycle table
  - power_budget_summary.txt   scalar summary (orbit-avg power, peak, energy)
  - figures/power_profile.png  instantaneous bus power vs. orbit time
  - figures/mode_energy.png    per-mode energy contribution (bar chart)

Usage:
    python scripts/run_power_budget.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from power_budget.budget import build_power_budget  # noqa: E402
from power_budget.energy import power_profile  # noqa: E402

from mission_baseline import BASELINE_SCHEDULE, ORBIT  # noqa: E402

RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    FIGURES_DIR.mkdir(exist_ok=True)

    budget = build_power_budget(BASELINE_SCHEDULE, ORBIT)

    # --- table -------------------------------------------------------
    table_path = RESULTS_DIR / "power_budget_table.csv"
    budget.table.to_csv(table_path)
    print(f"Wrote {table_path.relative_to(REPO_ROOT)}")
    print()
    print(budget.table.to_string(float_format=lambda x: f"{x:,.3f}"))
    print()
    print(budget.summary())

    # --- scalar summary text file ------------------------------------
    summary_path = RESULTS_DIR / "power_budget_summary.txt"
    summary_path.write_text(budget.summary() + "\n")
    print(f"\nWrote {summary_path.relative_to(REPO_ROOT)}")

    # --- figure 1: instantaneous power profile ------------------------
    t_s, p_w = power_profile(BASELINE_SCHEDULE, dt_s=1.0)
    t_min = t_s / 60.0

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(t_min, p_w, drawstyle="steps-post", color="#1f6f8b", linewidth=1.6)
    ax.axvspan(
        ORBIT.eclipse_start_s / 60.0,
        ORBIT.eclipse_end_s / 60.0,
        color="0.85",
        zorder=0,
        label="eclipse",
    )
    ax.axhline(
        budget.orbit_average_power_w,
        color="#c1440e",
        linestyle="--",
        linewidth=1.2,
        label=f"orbit-avg = {budget.orbit_average_power_w:.2f} W",
    )
    ax.axhline(
        budget.peak_power_w,
        color="#7a1f2b",
        linestyle=":",
        linewidth=1.2,
        label=f"peak = {budget.peak_power_w:.2f} W",
    )
    ax.set_xlabel("Orbit elapsed time [min]")
    ax.set_ylabel("Bus power [W]")
    ax.set_title("Baseline mission: instantaneous bus power over one orbit")
    ax.set_xlim(0, ORBIT.period_s / 60.0)
    ax.set_ylim(0, budget.peak_power_w * 1.15)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    profile_path = FIGURES_DIR / "power_profile.png"
    fig.savefig(profile_path, dpi=150)
    plt.close(fig)
    print(f"Wrote {profile_path.relative_to(REPO_ROOT)}")

    # --- figure 2: per-mode energy contribution ------------------------
    table_sorted = budget.table.sort_values("energy_wh", ascending=True)
    fig2, ax2 = plt.subplots(figsize=(7, 4))
    bars = ax2.barh(
        table_sorted.index, table_sorted["energy_wh"], color="#2e7d5b"
    )
    for bar, (mode, row) in zip(bars, table_sorted.iterrows()):
        ax2.text(
            bar.get_width() + 0.01 * table_sorted["energy_wh"].max(),
            bar.get_y() + bar.get_height() / 2,
            f"{row['energy_wh']:.2f} Wh ({row['duty_cycle']*100:.1f}% duty)",
            va="center",
            fontsize=8,
        )
    ax2.set_xlabel("Energy per orbit [Wh]")
    ax2.set_title("Baseline mission: energy contribution by operating mode")
    ax2.set_xlim(0, table_sorted["energy_wh"].max() * 1.35)
    ax2.grid(True, axis="x", alpha=0.3)
    fig2.tight_layout()
    energy_path = FIGURES_DIR / "mode_energy.png"
    fig2.savefig(energy_path, dpi=150)
    plt.close(fig2)
    print(f"Wrote {energy_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
