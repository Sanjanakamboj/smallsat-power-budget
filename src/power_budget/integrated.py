"""Integrated EPS design representation and margin definitions (Milestone 4).

This module represents the **fixed, selected** EPS hardware (array
area, battery capacity, and the representative EPS efficiency/
degradation assumptions that describe how that hardware actually
performs) separately from the **mission requirement** it must satisfy
on any given orbit. Milestones 2 and 3 answered "how big must the
array/battery be"; Milestone 4 asks "given that we have *this*
array and *this* battery, does it work" -- under nominal conditions,
a deterministic robust corner, and a Monte Carlo ensemble of mission/
EPS uncertainty (see :mod:`power_budget.robustness`).

Requirements vs. capabilities
------------------------------
- **Requirement**: what a given mission scenario (schedule + orbit)
  demands of the EPS -- sunlight/eclipse energy, battery withdrawal,
  peak load. Computed fresh from M1's :class:`~power_budget.budget.PowerBudget`
  for whatever scenario is being evaluated.
- **Capability**: what the *fixed* :class:`EPSDesign` can deliver --
  array electrical output (BOL/EOL), battery usable energy at the
  allowable DoD. Computed from the design's own area/capacity and
  power-density/degradation assumptions, independent of any one
  mission scenario.

Margins compare requirement against capability for a *specific*
scenario; they are never collapsed into one ambiguous "EPS margin" --
solar energy, array power, battery usable energy, and recharge time
each get their own explicit ratio (see :func:`compute_margins`).

Avoiding double-counting
--------------------------
The array area and battery capacity captured in :class:`EPSDesign` are
the Milestone-2/3 **selected** (already margined) values -- M2's
`design_margin` (25%) and M3's `capacity_margin` (25%) are baked into
those areas/capacities once, at selection time. When this module (or
:mod:`power_budget.robustness`) evaluates that fixed design against a
*varied* mission/EPS-performance scenario, it compares the design's
raw physical capability directly against the scenario's raw physical
requirement -- it never reapplies `design_margin` or `capacity_margin`
on top of an already-margined selection. This is documented explicitly
here and in `docs/integrated_eps_methodology.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from power_budget.budget import PowerBudget
    from power_budget.solar import SolarArraySizingResult
    from power_budget.battery import BatterySizingResult


@dataclass(frozen=True)
class EPSDesign:
    """A fixed, selected EPS hardware configuration.

    This dataclass does not resize itself -- every field is a
    *committed* design choice or a representative technology
    assumption describing how that committed hardware performs.

    Attributes
    ----------
    array_area_m2:
        Selected solar-array area, m^2 (Milestone-2 selected value,
        already carrying M2's design margin).
    array_bol_density_w_m2, array_eol_density_w_m2:
        Nominal BOL/EOL usable array power density, W/m^2 (Milestone-2
        assumptions: S0 * eta_cell * f_array [* f_eol for EOL]).
    eta_sun_path, eta_recharge_path:
        Nominal array-to-sunlight-load and array-to-battery charge-path
        efficiencies (Milestone-2 assumptions).
    battery_capacity_bol_wh:
        Selected battery BOL nameplate capacity, Wh (Milestone-3
        selected, rounded value, already carrying M3's capacity
        margin).
    battery_f_cap_eol:
        Nominal EOL battery capacity retention factor (Milestone-3
        assumption).
    dod_max:
        Maximum allowable depth of discharge -- an *operational policy
        limit*, not a physical uncertainty; used as the pass/fail
        threshold throughout Milestone 4, never sampled as uncertain.
    eta_discharge:
        Nominal battery discharge-path efficiency (Milestone-3
        assumption).
    """

    array_area_m2: float
    array_bol_density_w_m2: float
    array_eol_density_w_m2: float
    eta_sun_path: float
    eta_recharge_path: float
    battery_capacity_bol_wh: float
    battery_f_cap_eol: float
    dod_max: float
    eta_discharge: float

    def __post_init__(self) -> None:
        if self.array_area_m2 <= 0:
            raise ValueError(f"array_area_m2 must be > 0, got {self.array_area_m2!r}")
        if self.battery_capacity_bol_wh <= 0:
            raise ValueError(
                f"battery_capacity_bol_wh must be > 0, got {self.battery_capacity_bol_wh!r}"
            )
        for name in ("array_bol_density_w_m2", "array_eol_density_w_m2"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        for name in ("eta_sun_path", "eta_recharge_path", "battery_f_cap_eol", "eta_discharge"):
            v = getattr(self, name)
            if not (0.0 < v <= 1.0):
                raise ValueError(f"{name} must be in (0, 1], got {v!r}")
        if not (0.0 < self.dod_max <= 1.0):
            raise ValueError(f"dod_max must be in (0, 1], got {self.dod_max!r}")

    @property
    def array_power_bol_w(self) -> float:
        """Nominal BOL array electrical output, watts."""
        return self.array_area_m2 * self.array_bol_density_w_m2

    @property
    def array_power_eol_w(self) -> float:
        """Nominal EOL array electrical output, watts."""
        return self.array_area_m2 * self.array_eol_density_w_m2

    @property
    def battery_capacity_eol_wh(self) -> float:
        """Nominal EOL battery capacity, Wh."""
        return self.battery_capacity_bol_wh * self.battery_f_cap_eol

    @property
    def battery_capacity_eol_j(self) -> float:
        return self.battery_capacity_eol_wh * 3600.0

    @property
    def battery_usable_energy_eol_j(self) -> float:
        """Usable battery energy at EOL and the allowable DoD, joules."""
        return self.dod_max * self.battery_capacity_eol_j


def eps_design_from_baseline(
    solar_result: "SolarArraySizingResult", battery_result: "BatterySizingResult"
) -> EPSDesign:
    """Build the fixed :class:`EPSDesign` from the accepted M2/M3
    baseline sizing results, exactly as selected (no re-sizing)."""
    return EPSDesign(
        array_area_m2=solar_result.area_m2,
        array_bol_density_w_m2=solar_result.bol_density_w_m2,
        array_eol_density_w_m2=solar_result.eol_density_w_m2,
        eta_sun_path=solar_result.config.eta_sun_path,
        eta_recharge_path=solar_result.config.eta_recharge_path,
        battery_capacity_bol_wh=battery_result.selected_capacity_wh,
        battery_f_cap_eol=battery_result.config.f_cap_eol,
        dod_max=battery_result.config.dod_max,
        eta_discharge=battery_result.config.eta_discharge,
    )


# ---------------------------------------------------------------------------
# Requirement extraction (from any PowerBudget scenario)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MissionRequirement:
    """Requirement quantities extracted from a specific mission scenario."""

    t_sun_s: float
    e_sun_j: float
    e_eclipse_j: float
    peak_load_w: float
    orbit_energy_j: float


def requirement_from_power_budget(power_budget: "PowerBudget") -> MissionRequirement:
    sun = power_budget.phase_energy["sunlight"]
    ecl = power_budget.phase_energy["eclipse"]
    return MissionRequirement(
        t_sun_s=sun.duration_s,
        e_sun_j=sun.energy_j,
        e_eclipse_j=ecl.energy_j,
        peak_load_w=power_budget.peak_power_w,
        orbit_energy_j=power_budget.total_energy_j,
    )


# ---------------------------------------------------------------------------
# Margins (§5) -- kept explicit and separate, never collapsed into one number
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EPSMargins:
    """Four explicit, non-collapsed EPS margins for one scenario against
    one fixed :class:`EPSDesign`, evaluated at EOL (the conservative,
    worst-case-in-time basis)."""

    solar_energy_margin: float  # M_E = E_available,sun / E_required,sun+recharge
    array_power_margin: float  # M_P = P_array,EOL / P_array,required(raw)
    battery_energy_margin: float  # M_B = DoD_max * C_available,EOL / E_batt,withdrawal
    recharge_time_margin: float  # M_R = t_sunlight / t_recharge (None-safe: inf if t_recharge==0)


def compute_margins(
    design: EPSDesign,
    requirement: MissionRequirement,
    t_recharge_s: float | None,
) -> EPSMargins:
    """Compute the four Milestone-4 EPS margins for one scenario.

    Uses the design's own EOL array output and EOL battery capacity --
    the conservative, end-of-mission-life capability basis -- against
    the scenario's raw physical requirement. No additional design
    margin is reapplied here (see module docstring, "Avoiding
    double-counting").
    """
    t_sun_s = requirement.t_sun_s
    if t_sun_s <= 0:
        raise ValueError("requirement.t_sun_s must be > 0")

    # Solar energy margin: raw array generation over sunlight vs. the
    # raw-equivalent requirement (sunlight loads / eta_s + eclipse
    # recharge / eta_c) -- same construction as M2's sizing equation.
    e_required_raw_j = (
        requirement.e_sun_j / design.eta_sun_path
        + requirement.e_eclipse_j / design.eta_recharge_path
    )
    e_available_raw_j = design.array_power_eol_w * t_sun_s
    solar_energy_margin = (
        e_available_raw_j / e_required_raw_j if e_required_raw_j > 0 else float("inf")
    )

    # Array power margin: EOL array output vs. the raw sunlight-only
    # power that would be required to meet the same energy balance
    # (M2's P_SA,raw construction, unmargined).
    p_required_raw_w = e_required_raw_j / t_sun_s
    array_power_margin = (
        design.array_power_eol_w / p_required_raw_w if p_required_raw_w > 0 else float("inf")
    )

    # Battery energy margin: usable EOL battery energy at DoD_max vs.
    # the actual battery-side eclipse withdrawal.
    withdrawal_j = requirement.e_eclipse_j / design.eta_discharge
    battery_energy_margin = (
        design.battery_usable_energy_eol_j / withdrawal_j if withdrawal_j > 0 else float("inf")
    )

    # Recharge-time margin.
    if t_recharge_s is None or t_recharge_s <= 0:
        recharge_time_margin = float("inf")
    else:
        recharge_time_margin = t_sun_s / t_recharge_s

    return EPSMargins(
        solar_energy_margin=solar_energy_margin,
        array_power_margin=array_power_margin,
        battery_energy_margin=battery_energy_margin,
        recharge_time_margin=recharge_time_margin,
    )


# ---------------------------------------------------------------------------
# Nominal design verification (§6) -- explicit pass/fail criteria
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NominalVerification:
    """Explicit pass/fail verification of the fixed design against the
    nominal (unperturbed) baseline mission scenario."""

    peak_load_supported: bool
    orbit_energy_closes: bool
    eclipse_energy_supported: bool
    dod_within_limit: bool
    battery_returns_to_steady_state: bool
    recharge_completes_in_sunlight: bool
    eol_array_closes: bool
    eol_battery_closes: bool

    @property
    def all_pass(self) -> bool:
        return all(
            (
                self.peak_load_supported,
                self.orbit_energy_closes,
                self.eclipse_energy_supported,
                self.dod_within_limit,
                self.battery_returns_to_steady_state,
                self.recharge_completes_in_sunlight,
                self.eol_array_closes,
                self.eol_battery_closes,
            )
        )
