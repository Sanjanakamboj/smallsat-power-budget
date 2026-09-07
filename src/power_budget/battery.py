"""Battery sizing and eclipse energy storage (Milestone 3).

Core idea
---------
Milestone 2 sized the solar array to generate enough raw sunlight
energy to cover sunlight loads and *deposit* ``E_eclipse`` worth of
usable energy into storage (``eta_recharge_path`` in
:class:`~power_budget.solar.SolarArrayConfig`, deliberately excluding
battery *discharge* losses -- that is this module's job). Milestone 3
closes the loop on the storage side: given the load-side eclipse
energy demand ``E_e`` (reused directly from the Milestone-1
:class:`~power_budget.budget.PowerBudget`), how much energy must
actually be *withdrawn* from the battery (after discharge-path
losses), what nameplate capacity does that require under an allowable
depth-of-discharge limit, explicit design margin, and end-of-life
capacity retention, and does the Milestone-2 array generate enough
surplus during sunlight to restore that withdrawal every orbit.

Battery-side energy-flow convention
------------------------------------
Let ``eta_d`` be the battery-to-bus discharge-path efficiency. The
energy actually withdrawn from stored battery energy during eclipse is

    E_batt,out = E_e / eta_d                              [J]

which is strictly larger than the load-side eclipse energy ``E_e`` --
exactly analogous to how Milestone 2's raw array requirement exceeds
the delivered load energy. This is the quantity a capacity/DoD
calculation must use, never ``E_e`` directly
(:func:`battery_withdrawal_j`).

Depth of discharge and capacity
---------------------------------
    DoD          = E_withdrawn / C_reference               [-]
    C_raw        = E_batt,out / DoD_max                     [J]
    C_design,EOL = SF_C * C_raw                              [J]
    C_BOL        = C_design,EOL / f_cap,EOL                  [J]

``C_raw`` is sized against ``DoD_max`` directly from the withdrawal, so
it is already an *end-of-life-basis* usable-capacity requirement (the
battery must not be cycled deeper than ``DoD_max`` even after capacity
fade). ``SF_C`` (design/uncertainty margin) and ``f_cap,EOL``
(end-of-life capacity retention) are applied as two separate,
explicitly labeled multipliers -- never folded into ``DoD_max`` or
into each other. ``f_cap,EOL`` is a *stated assumption*, not a derived
cycle-life prediction, and is a distinct concept from Milestone 2's
photovoltaic ``f_eol`` (array power degradation).

State of charge
-----------------
    SOC = E_stored / C_available,   0 <= SOC <= 1
    DoD = 1 - SOC                    (only meaningful measured from a full charge)

:func:`simulate_orbit_soc` integrates the battery state of charge over
one orbit using the same piecewise-constant schedule/eclipse-boundary
sweep technique as
:func:`power_budget.energy.energy_by_phase`: during sunlight, the
array (at its Milestone-2 design power) covers sunlight loads through
``eta_sun_path`` and any surplus charges the battery through
``eta_recharge_path``, clipped at full capacity (excess is dumped/
regulated away, e.g. by a shunt regulator -- not stored); during
eclipse, the battery discharges to the bus through ``eta_discharge``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from power_budget.budget import PowerBudget
    from power_budget.solar import SolarArrayConfig, SolarArraySizingResult

from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule

_TOL_S = 1e-6


def _check_unit_interval(name: str, value: float) -> None:
    if not (0.0 < value <= 1.0):
        raise ValueError(f"{name} must be in (0, 1], got {value!r}")


@dataclass(frozen=True)
class BatteryConfig:
    """Representative battery/EPS assumptions for Milestone 3 sizing.

    All values are stated, representative systems-level engineering
    assumptions -- no commercial battery cell/pack is selected or
    implied.

    Attributes
    ----------
    eta_discharge:
        Battery-to-bus discharge-path efficiency, dimensionless,
        in (0, 1]. Default 0.95 (representative discharge-converter +
        harness loss).
    dod_max:
        Maximum allowable depth of discharge for the design cycle,
        dimensionless, in (0, 1]. Default 0.25 (25%), representative
        of a conservative, frequently-cycled LEO Li-ion design point
        chosen for cycle-life margin (no cycle-life model is fit here
        -- this is a stated design choice, not a derived result).
    capacity_margin:
        Explicit capacity design/uncertainty margin ``SF_C``,
        dimensionless, >= 1. Default 1.25 (25%), kept strictly
        separate from ``dod_max``.
    f_cap_eol:
        End-of-life capacity retention factor relative to BOL nameplate
        capacity, dimensionless, in (0, 1]. Default 0.80. A stated
        assumption, not a derived cycle-life/calendar-aging model, and
        distinct from Milestone 2's photovoltaic ``f_eol``.
    capacity_step_wh:
        Rounding granularity, in Wh, used by
        :func:`select_design_capacity_wh` to choose a practical
        selected design capacity above the analytical minimum. Default
        5.0 Wh (representative of common small-battery-pack capacity
        granularity).
    """

    eta_discharge: float = 0.95
    dod_max: float = 0.25
    capacity_margin: float = 1.25
    f_cap_eol: float = 0.80
    capacity_step_wh: float = 5.0

    def __post_init__(self) -> None:
        _check_unit_interval("eta_discharge", self.eta_discharge)
        _check_unit_interval("dod_max", self.dod_max)
        _check_unit_interval("f_cap_eol", self.f_cap_eol)
        if self.capacity_margin < 1.0:
            raise ValueError(
                f"capacity_margin must be >= 1.0, got {self.capacity_margin!r}"
            )
        if self.capacity_step_wh <= 0:
            raise ValueError(
                f"capacity_step_wh must be > 0, got {self.capacity_step_wh!r}"
            )


# ---------------------------------------------------------------------------
# Sizing chain
# ---------------------------------------------------------------------------
def battery_withdrawal_j(e_eclipse_j: float, config: BatteryConfig) -> float:
    """Energy withdrawn from stored battery energy during eclipse, joules.

    ``E_batt,out = E_e / eta_discharge``
    """
    if e_eclipse_j < 0:
        raise ValueError(f"e_eclipse_j must be >= 0, got {e_eclipse_j!r}")
    return e_eclipse_j / config.eta_discharge


def raw_capacity_j(withdrawal_j: float, config: BatteryConfig) -> float:
    """Raw (pre-margin) required usable capacity, joules.

    ``C_raw = E_batt,out / DoD_max``
    """
    if withdrawal_j < 0:
        raise ValueError(f"withdrawal_j must be >= 0, got {withdrawal_j!r}")
    return withdrawal_j / config.dod_max


def design_capacity_eol_j(raw_capacity_j_: float, config: BatteryConfig) -> float:
    """Design (margined) required usable capacity at EOL, joules.

    ``C_design,EOL = SF_C * C_raw``
    """
    if raw_capacity_j_ < 0:
        raise ValueError(f"raw_capacity_j_ must be >= 0, got {raw_capacity_j_!r}")
    return config.capacity_margin * raw_capacity_j_


def bol_nameplate_capacity_j(design_capacity_eol_j_: float, config: BatteryConfig) -> float:
    """Required BOL nameplate capacity, joules.

    ``C_BOL = C_design,EOL / f_cap,EOL``
    """
    if design_capacity_eol_j_ < 0:
        raise ValueError(
            f"design_capacity_eol_j_ must be >= 0, got {design_capacity_eol_j_!r}"
        )
    return design_capacity_eol_j_ / config.f_cap_eol


def select_design_capacity_wh(min_required_wh: float, config: BatteryConfig) -> float:
    """Round the analytical minimum BOL nameplate capacity up to a
    practical selected design capacity.

    Rounding philosophy: round up to the nearest multiple of
    ``config.capacity_step_wh`` (default 5 Wh), representative of the
    capacity granularity available when a battery pack is assembled
    from a discrete number of series/parallel cells. The selected
    capacity is always >= the analytical minimum; it is never chosen
    by adjusting upstream assumptions.
    """
    if min_required_wh < 0:
        raise ValueError(f"min_required_wh must be >= 0, got {min_required_wh!r}")
    step = config.capacity_step_wh
    return math.ceil(min_required_wh / step - 1e-9) * step


# ---------------------------------------------------------------------------
# Recharge closure (M2 <-> M3 consistency)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RechargeClosureResult:
    """Independent verification that the Milestone-2 array generates
    enough sunlight surplus, through the *same* ``eta_recharge_path``
    used by Milestone 2, to restore the battery-side eclipse
    withdrawal (the stricter, discharge-loss-inclusive quantity that
    Milestone 2 explicitly deferred to Milestone 3).

    Attributes
    ----------
    available_recharge_j:
        Usable energy the array can deposit into the battery over the
        sunlight arc, after direct sunlight-load support and
        charge-path losses: ``eta_c * (P_SA,design * t_sun - E_s / eta_s)``.
    required_j:
        The battery-side withdrawal that must be restored,
        ``E_batt,out`` (joules).
    closes:
        ``True`` iff ``available_recharge_j >= required_j``.
    margin_fraction:
        ``available_recharge_j / required_j - 1``.
    """

    available_recharge_j: float
    required_j: float
    closes: bool
    margin_fraction: float


def verify_recharge_closure(
    e_sun_j: float,
    t_sun_s: float,
    p_sa_design_w: float,
    withdrawal_j: float,
    solar_config: "SolarArrayConfig",
) -> RechargeClosureResult:
    """Independently verify the array can restore the battery withdrawal.

    Recomputes the available sunlight recharge surplus directly from
    ``e_sun_j``/``t_sun_s``/``p_sa_design_w`` -- it does not reuse any
    cached Milestone-2 intermediate energy-closure result -- and
    compares it against the battery-side withdrawal (not the load-side
    ``E_e``), which is the physically correct quantity that must be
    restored each orbit.
    """
    if t_sun_s <= 0:
        raise ValueError(f"t_sun_s must be > 0, got {t_sun_s!r}")
    if withdrawal_j < 0:
        raise ValueError(f"withdrawal_j must be >= 0, got {withdrawal_j!r}")

    raw_sun_load_j = e_sun_j / solar_config.eta_sun_path
    raw_surplus_j = p_sa_design_w * t_sun_s - raw_sun_load_j
    available_j = max(raw_surplus_j, 0.0) * solar_config.eta_recharge_path

    margin_fraction = (
        available_j / withdrawal_j - 1.0 if withdrawal_j > 0 else float("inf")
    )
    return RechargeClosureResult(
        available_recharge_j=available_j,
        required_j=withdrawal_j,
        closes=available_j >= withdrawal_j,
        margin_fraction=margin_fraction,
    )


# ---------------------------------------------------------------------------
# One-orbit SOC simulation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SOCProfile:
    """Piecewise-exact state-of-charge trace over one orbit.

    ``t_s`` / ``soc`` are parallel tuples of boundary points (every
    schedule-entry edge, plus the eclipse boundary), so linear
    interpolation between consecutive points reproduces the exact
    (piecewise-linear-in-energy) trace -- no numerical integration
    error, consistent with the rest of this package's analytic
    approach to piecewise-constant power.
    """

    t_s: tuple[float, ...]
    soc: tuple[float, ...]
    capacity_j: float
    initial_soc: float
    min_soc: float
    soc_at_eclipse_entry: float
    final_soc: float
    t_recharge_s: float | None
    clipped_energy_j: float


def simulate_orbit_soc(
    schedule: OrbitSchedule,
    orbit: OrbitGeometry,
    p_sa_design_w: float,
    solar_config: "SolarArrayConfig",
    battery_config: BatteryConfig,
    capacity_j: float,
    initial_soc: float | None = None,
) -> SOCProfile:
    """Integrate battery SOC over one orbit.

    Sunlight: array (at ``p_sa_design_w``) covers the raw sunlight-load
    draw (``P_load / eta_sun_path``); any surplus charges the battery
    at rate ``surplus * eta_recharge_path``, clipped so stored energy
    never exceeds ``capacity_j`` (excess is dumped, e.g. by a shunt
    regulator -- not modeled in detail, out of scope per §29).

    Eclipse: battery discharges to the bus at rate
    ``P_load / eta_discharge``.

    If ``initial_soc`` is not given, it is set to the periodic
    steady-state value ``1 - DoD_actual`` where ``DoD_actual`` is the
    actual (not maximum-allowable) depth of discharge implied by this
    orbit's eclipse withdrawal against ``capacity_j`` -- i.e. the SOC
    right after the *previous* eclipse ends, which is exactly ``t=0``
    in this package's time convention (see :mod:`power_budget.orbit`).
    This makes the returned profile close periodically by construction
    whenever the array fully recharges before eclipse begins (asserted
    in tests), and is clearly flagged (via ``t_recharge_s`` and
    ``clipped_energy_j``) when it does not.
    """
    if capacity_j <= 0:
        raise ValueError(f"capacity_j must be > 0, got {capacity_j!r}")
    if abs(schedule.orbit_period_s - orbit.period_s) > _TOL_S:
        raise ValueError("schedule.orbit_period_s must match orbit.period_s")

    if initial_soc is None:
        # Periodic steady-state: t=0 is the instant eclipse ends, so the
        # battery is at its cycle minimum right then.
        from power_budget.energy import energy_by_phase  # local import: avoid cycle

        phase_e = energy_by_phase(schedule, orbit)
        e_ecl_j = phase_e["eclipse"].energy_j
        withdrawal_j = battery_withdrawal_j(e_ecl_j, battery_config)
        dod_actual = withdrawal_j / capacity_j
        initial_soc = max(0.0, 1.0 - dod_actual)

    if not (0.0 <= initial_soc <= 1.0):
        raise ValueError(f"initial_soc must be in [0, 1], got {initial_soc!r}")

    boundaries = {0.0, orbit.period_s, orbit.eclipse_start_s}
    for e in schedule.entries:
        boundaries.add(e.start_s)
        boundaries.add(e.end_s)
    sorted_bounds = sorted(boundaries)

    t_trace = [0.0]
    soc_trace = [initial_soc]
    e_stored = initial_soc * capacity_j
    clipped_energy_j = 0.0
    min_soc = initial_soc
    soc_at_eclipse_entry = initial_soc
    t_recharge_s: float | None = None
    full_reached = math.isclose(initial_soc, 1.0, abs_tol=1e-9)
    if full_reached:
        t_recharge_s = 0.0

    for a, b in zip(sorted_bounds, sorted_bounds[1:]):
        span = b - a
        if span <= _TOL_S:
            continue
        mid = 0.5 * (a + b)
        power_w = schedule.mode_at(mid).power_w
        phase = orbit.phase_at(mid)

        if phase == "sunlight":
            raw_load_w = power_w / solar_config.eta_sun_path
            surplus_raw_w = p_sa_design_w - raw_load_w
            if surplus_raw_w < 0:
                raise ValueError(
                    "Sunlight-phase raw load draw "
                    f"({raw_load_w:.3f} W) exceeds design array output "
                    f"({p_sa_design_w:.3f} W) at t={mid:.1f} s -- battery "
                    "assist during sunlight is out of scope for this "
                    "simulation (see module docstring)."
                )
            e_add_j = surplus_raw_w * solar_config.eta_recharge_path * span
            e_new_unclipped = e_stored + e_add_j
            if e_new_unclipped > capacity_j:
                clipped_energy_j += e_new_unclipped - capacity_j
                e_new = capacity_j
            else:
                e_new = e_new_unclipped
        else:  # eclipse
            e_remove_j = (power_w / battery_config.eta_discharge) * span
            e_new_unclipped = e_stored - e_remove_j
            if e_new_unclipped < -1e-6:
                raise ValueError(
                    f"Battery undersized: stored energy would go negative "
                    f"at t={b:.1f} s (capacity_j={capacity_j:.1f})"
                )
            e_new = max(e_new_unclipped, 0.0)

        soc_new = e_new / capacity_j
        if not full_reached and soc_new >= 1.0 - 1e-9:
            # Linear interpolation within this segment for a more precise
            # recharge-completion time (segment power is constant, so the
            # stored-energy trace is exactly linear in time here). Uses the
            # *unclipped* projected energy so a segment that overshoots
            # full capacity still resolves the correct crossing instant,
            # not the segment's end time.
            if e_new_unclipped > e_stored:
                frac = (capacity_j - e_stored) / (e_new_unclipped - e_stored)
            else:
                frac = 0.0
            t_recharge_s = a + frac * span
            full_reached = True

        t_trace.append(b)
        soc_trace.append(soc_new)
        e_stored = e_new
        min_soc = min(min_soc, soc_new)
        if math.isclose(b, orbit.eclipse_start_s, abs_tol=1e-6):
            soc_at_eclipse_entry = soc_new

    return SOCProfile(
        t_s=tuple(t_trace),
        soc=tuple(soc_trace),
        capacity_j=capacity_j,
        initial_soc=initial_soc,
        min_soc=min_soc,
        soc_at_eclipse_entry=soc_at_eclipse_entry,
        final_soc=soc_trace[-1],
        t_recharge_s=t_recharge_s,
        clipped_energy_j=clipped_energy_j,
    )


# ---------------------------------------------------------------------------
# Top-level battery sizing result
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BatterySizingResult:
    """Full Milestone-3 battery sizing result for one orbit."""

    power_budget: "PowerBudget"
    solar_result: "SolarArraySizingResult"
    config: BatteryConfig
    e_eclipse_j: float
    withdrawal_j: float
    raw_capacity_j: float
    design_capacity_eol_j: float
    bol_nameplate_capacity_j: float
    selected_capacity_wh: float
    actual_dod: float
    closure: RechargeClosureResult
    soc_profile: SOCProfile

    @property
    def selected_capacity_j(self) -> float:
        return self.selected_capacity_wh * 3600.0

    def summary(self) -> str:
        c = self.closure
        p = self.soc_profile
        recharge_frac = (
            p.t_recharge_s / self.solar_result.t_sun_s
            if p.t_recharge_s is not None
            else float("nan")
        )
        return (
            f"Eclipse load energy: {self.e_eclipse_j / 3600:.2f} Wh\n"
            f"Battery withdrawal (after eta_d): {self.withdrawal_j / 3600:.2f} Wh\n"
            f"Raw capacity (DoD_max={self.config.dod_max:.2f}): "
            f"{self.raw_capacity_j / 3600:.2f} Wh\n"
            f"Design capacity @ EOL (SF_C={self.config.capacity_margin:.2f}): "
            f"{self.design_capacity_eol_j / 3600:.2f} Wh\n"
            f"Required BOL nameplate (f_cap,EOL={self.config.f_cap_eol:.2f}): "
            f"{self.bol_nameplate_capacity_j / 3600:.2f} Wh\n"
            f"Selected design capacity: {self.selected_capacity_wh:.1f} Wh\n"
            f"Actual DoD at selected capacity: {self.actual_dod * 100:.1f}%\n"
            f"Minimum SOC over orbit: {p.min_soc * 100:.1f}%\n"
            f"Recharge closure: available {c.available_recharge_j / 3600:.2f} Wh "
            f"vs required {c.required_j / 3600:.2f} Wh "
            f"(margin {c.margin_fraction * 100:.1f}%, closes={c.closes})\n"
            f"Recharge time: {p.t_recharge_s / 60 if p.t_recharge_s else float('nan'):.1f} min "
            f"({recharge_frac * 100:.1f}% of sunlight duration)"
        )


def size_battery(
    power_budget: "PowerBudget",
    solar_result: "SolarArraySizingResult",
    battery_config: BatteryConfig,
) -> BatterySizingResult:
    """Compute the full Milestone-3 battery sizing from a Milestone-1
    :class:`~power_budget.budget.PowerBudget` and a Milestone-2
    :class:`~power_budget.solar.SolarArraySizingResult`.

    Reuses ``power_budget.phase_energy["eclipse"].energy_j`` and
    ``solar_result`` (schedule, orbit, design array power, solar
    config) directly -- neither the load model nor the array sizing is
    recreated here.
    """
    e_ecl_j = power_budget.phase_energy["eclipse"].energy_j

    withdrawal_j = battery_withdrawal_j(e_ecl_j, battery_config)
    raw_j = raw_capacity_j(withdrawal_j, battery_config)
    design_eol_j = design_capacity_eol_j(raw_j, battery_config)
    bol_j = bol_nameplate_capacity_j(design_eol_j, battery_config)
    bol_wh = bol_j / 3600.0
    selected_wh = select_design_capacity_wh(bol_wh, battery_config)
    selected_j = selected_wh * 3600.0

    actual_dod = withdrawal_j / selected_j

    closure = verify_recharge_closure(
        e_sun_j=solar_result.e_sun_j,
        t_sun_s=solar_result.t_sun_s,
        p_sa_design_w=solar_result.p_sa_design_w,
        withdrawal_j=withdrawal_j,
        solar_config=solar_result.config,
    )

    profile = simulate_orbit_soc(
        schedule=power_budget.schedule,
        orbit=power_budget.orbit,
        p_sa_design_w=solar_result.p_sa_design_w,
        solar_config=solar_result.config,
        battery_config=battery_config,
        capacity_j=selected_j,
    )

    return BatterySizingResult(
        power_budget=power_budget,
        solar_result=solar_result,
        config=battery_config,
        e_eclipse_j=e_ecl_j,
        withdrawal_j=withdrawal_j,
        raw_capacity_j=raw_j,
        design_capacity_eol_j=design_eol_j,
        bol_nameplate_capacity_j=bol_j,
        selected_capacity_wh=selected_wh,
        actual_dod=actual_dod,
        closure=closure,
        soc_profile=profile,
    )
