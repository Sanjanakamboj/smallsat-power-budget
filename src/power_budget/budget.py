"""Top-level power-budget summary.

Ties together a :class:`~power_budget.schedule.OrbitSchedule` and
:class:`~power_budget.orbit.OrbitGeometry` into the deliverable of
Milestone 1: a per-mode power-budget table plus whole-orbit scalar
metrics (orbit-average power, peak power, sunlight/eclipse energy).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from power_budget.energy import (
    PhaseEnergy,
    energy_by_phase,
    orbit_average_power_w,
    peak_power_w,
    total_energy_j,
)
from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule


@dataclass(frozen=True)
class PowerBudget:
    """Full Milestone-1 power-budget result for one orbit.

    Attributes
    ----------
    schedule, orbit:
        The inputs the budget was computed from.
    table:
        Per-mode summary as a :class:`pandas.DataFrame` with one row per
        *unique mode name* (spans of the same mode are aggregated),
        columns: ``power_w``, ``duty_cycle``, ``duration_s``,
        ``energy_j``, ``energy_wh``, ``n_spans``.
    orbit_average_power_w, peak_power_w, total_energy_j:
        Whole-orbit scalar metrics, watts / watts / joules.
    phase_energy:
        Dict with keys ``"sunlight"`` / ``"eclipse"`` -> ``PhaseEnergy``.
    """

    schedule: OrbitSchedule
    orbit: OrbitGeometry
    table: pd.DataFrame
    orbit_average_power_w: float
    peak_power_w: float
    total_energy_j: float
    phase_energy: dict[str, PhaseEnergy]

    def summary(self) -> str:
        """Human-readable one-paragraph summary of the budget."""
        sun = self.phase_energy["sunlight"]
        ecl = self.phase_energy["eclipse"]
        return (
            f"Orbit period {self.orbit.period_s / 60:.1f} min "
            f"(sunlight {sun.duration_s / 60:.1f} min, "
            f"eclipse {ecl.duration_s / 60:.1f} min, "
            f"eclipse fraction {self.orbit.eclipse_fraction:.3f})\n"
            f"Orbit-average power: {self.orbit_average_power_w:.2f} W\n"
            f"Peak power: {self.peak_power_w:.2f} W\n"
            f"Total energy/orbit: {self.total_energy_j / 3600:.2f} Wh "
            f"({self.total_energy_j:.0f} J)\n"
            f"Sunlight energy: {sun.energy_wh:.2f} Wh "
            f"(avg {sun.average_power_w:.2f} W)\n"
            f"Eclipse energy: {ecl.energy_wh:.2f} Wh "
            f"(avg {ecl.average_power_w:.2f} W)"
        )


def build_power_budget(schedule: OrbitSchedule, orbit: OrbitGeometry) -> PowerBudget:
    """Compute the full Milestone-1 power budget for a schedule/orbit pair."""
    rows: dict[str, dict[str, float]] = {}
    for entry in schedule.entries:
        row = rows.setdefault(
            entry.mode.name,
            {
                "power_w": entry.mode.power_w,
                "duration_s": 0.0,
                "energy_j": 0.0,
                "n_spans": 0,
            },
        )
        if row["power_w"] != entry.mode.power_w:
            raise ValueError(
                f"Mode {entry.mode.name!r} appears with inconsistent power_w "
                f"values ({row['power_w']!r} vs {entry.mode.power_w!r})"
            )
        row["duration_s"] += entry.duration_s
        row["energy_j"] += entry.energy_j
        row["n_spans"] += 1

    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "mode"
    table["duty_cycle"] = table["duration_s"] / schedule.orbit_period_s
    table["energy_wh"] = table["energy_j"] / 3600.0
    table["n_spans"] = table["n_spans"].astype(int)
    table = table[
        ["power_w", "duty_cycle", "duration_s", "energy_j", "energy_wh", "n_spans"]
    ].sort_values("energy_j", ascending=False)

    return PowerBudget(
        schedule=schedule,
        orbit=orbit,
        table=table,
        orbit_average_power_w=orbit_average_power_w(schedule),
        peak_power_w=peak_power_w(schedule),
        total_energy_j=total_energy_j(schedule),
        phase_energy=energy_by_phase(schedule, orbit),
    )
