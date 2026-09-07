"""Solar-array sizing: sunlight-only energy closure (Milestone 2).

Core idea
---------
The spacecraft load model (Milestone 1, :mod:`power_budget.budget`) is
the single source of truth for how much energy the spacecraft consumes
in sunlight (``E_s``) and in eclipse (``E_e``) over one orbit. This
module answers a *different* question than "what is the orbit-average
power": the array only exists, electrically, during the sunlight arc
(duration ``t_s``). In that window it must simultaneously

  1. power the sunlight-phase loads, and
  2. generate enough surplus energy to recharge whatever the
     spacecraft consumed during the preceding/following eclipse,

before the next eclipse begins. Both paths carry conversion losses, so
the raw electrical output the array must produce is strictly larger
than the electrical energy actually delivered to the loads/battery.

Sizing equation
----------------
Let ``eta_s`` be the array-to-sunlight-load path efficiency (regulation
+ harness between the array output bus and the loads operating in
sunlight) and ``eta_c`` be the *effective* eclipse-energy recharge-path
efficiency (battery charge-conversion losses incurred while storing
sunlight-generated energy for later eclipse discharge). Then the raw
required array electrical output is

    P_SA,raw = (E_s / eta_s + E_e / eta_c) / t_s        [W]

This is the equation used by :func:`required_array_power_raw_w`. It
is deliberately *not* ``P_avg = (E_s + E_e) / T_orbit``: the naive
average-power figure ignores both (a) that eclipse energy must be
regenerated within the shorter sunlight window rather than spread
across the whole orbit, and (b) conversion losses on each path. See
``scripts/size_solar_array.py`` for a direct numeric comparison.

Design margin is applied *after* the raw requirement, as a separate,
explicit multiplier (``design_margin`` in :class:`SolarArrayConfig`) --
it is never folded into a cell/array efficiency number, so the raw
requirement and the margin are always separately inspectable.

Power-density chain
--------------------
    p_BOL         = S0 * eta_cell * f_array
    p_usable,EOL  = p_BOL * f_EOL

where ``S0`` is the solar constant (representative, fixed, no
orbital-distance model), ``eta_cell`` is a representative
beginning-of-life photovoltaic conversion efficiency, ``f_array`` is a
single array-level derating factor lumping non-normal incidence,
packing, interconnects and practical utilization, and ``f_EOL`` is a
single end-of-life degradation factor. Degradation (``f_EOL``) and
design margin (``design_margin``) are kept strictly separate: one
derates the *technology* (how much power a given area produces after
mission life), the other inflates the *requirement* (how much power
the mission needs, including margin for load growth/uncertainty).

Required array area follows directly:

    A_SA = P_SA,design / p_usable,EOL                    [m^2]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from power_budget.budget import PowerBudget

# Representative solar constant near 1 AU. Treated as a fixed
# representative value for this milestone -- no orbital eccentricity /
# seasonal Sun-distance model is applied.
SOLAR_CONSTANT_W_M2 = 1361.0


def _check_unit_interval(name: str, value: float, *, allow_one: bool = True) -> None:
    upper_ok = value <= 1.0 if allow_one else value < 1.0
    if not (0.0 < value and upper_ok):
        bound = "(0, 1]" if allow_one else "(0, 1)"
        raise ValueError(f"{name} must be in {bound}, got {value!r}")


@dataclass(frozen=True)
class SolarArrayConfig:
    """Representative EPS/array assumptions for Milestone 2 sizing.

    Every efficiency/derating factor satisfies ``0 < value <= 1``
    (enforced in ``__post_init__``); ``design_margin`` satisfies
    ``design_margin >= 1``. All values here are stated representative
    engineering assumptions, not sourced hardware/vendor specifications.

    Attributes
    ----------
    s0_w_m2:
        Solar constant near 1 AU, W/m^2. Default 1361.0 (representative).
    eta_cell:
        Beginning-of-life photovoltaic cell conversion efficiency,
        dimensionless. Default 0.30, representative of a modern
        multi-junction smallsat cell (technology-class assumption, not
        a vendor part number).
    f_array:
        Single array-level derating factor lumping non-normal solar
        incidence, cell packing density, interconnect area, and
        practical panel utilization. Default 0.85.
    f_eol:
        End-of-life power degradation factor relative to BOL, from
        radiation and thermal-cycling degradation over the mission
        life. Default 0.85 (i.e. array delivers 85% of BOL power
        density at end of life). Kept strictly separate from
        ``design_margin``.
    eta_sun_path:
        Array-to-bus conversion/regulation/harness efficiency on the
        path that powers sunlight-phase loads directly. Default 0.90.
    eta_recharge_path:
        Effective efficiency of the path that stores sunlight-generated
        energy for later eclipse discharge (battery charge-conversion
        losses). Default 0.85. (Battery *discharge* efficiency is a
        battery-sizing concern, Milestone 3 -- not included here since
        this module only sizes how much energy must be put *into*
        storage during sunlight, not how it is drawn back out.)
    design_margin:
        Multiplicative design/load-growth margin applied to the raw
        array-power requirement, dimensionless, >= 1. Default 1.25
        (25%), a representative baseline for early-phase smallsat EPS
        sizing. Applied strictly after the raw requirement -- never
        folded into an efficiency term.
    """

    s0_w_m2: float = SOLAR_CONSTANT_W_M2
    eta_cell: float = 0.30
    f_array: float = 0.85
    f_eol: float = 0.85
    eta_sun_path: float = 0.90
    eta_recharge_path: float = 0.85
    design_margin: float = 1.25

    def __post_init__(self) -> None:
        if self.s0_w_m2 <= 0:
            raise ValueError(f"s0_w_m2 must be > 0, got {self.s0_w_m2!r}")
        _check_unit_interval("eta_cell", self.eta_cell)
        _check_unit_interval("f_array", self.f_array)
        _check_unit_interval("f_eol", self.f_eol)
        _check_unit_interval("eta_sun_path", self.eta_sun_path)
        _check_unit_interval("eta_recharge_path", self.eta_recharge_path)
        if self.design_margin < 1.0:
            raise ValueError(
                f"design_margin must be >= 1.0, got {self.design_margin!r}"
            )


def bol_power_density_w_m2(config: SolarArrayConfig) -> float:
    """Beginning-of-life usable array power density, W/m^2.

    ``p_BOL = S0 * eta_cell * f_array``
    """
    return config.s0_w_m2 * config.eta_cell * config.f_array


def eol_power_density_w_m2(config: SolarArrayConfig) -> float:
    """End-of-life usable array power density, W/m^2.

    ``p_usable,EOL = p_BOL * f_EOL``
    """
    return bol_power_density_w_m2(config) * config.f_eol


def required_array_power_raw_w(
    e_sun_j: float,
    e_eclipse_j: float,
    t_sun_s: float,
    config: SolarArrayConfig,
) -> float:
    """Raw (pre-margin) required array electrical output, watts.

    ``P_SA,raw = (E_s / eta_s + E_e / eta_c) / t_s``

    Parameters
    ----------
    e_sun_j, e_eclipse_j:
        Spacecraft energy consumed in sunlight / eclipse over one
        orbit, joules (reused directly from the Milestone-1
        :class:`~power_budget.budget.PowerBudget`, never recomputed
        here).
    t_sun_s:
        Sunlight arc duration, seconds. Must be > 0.
    """
    if t_sun_s <= 0:
        raise ValueError(f"t_sun_s must be > 0, got {t_sun_s!r}")
    if e_sun_j < 0 or e_eclipse_j < 0:
        raise ValueError("e_sun_j and e_eclipse_j must be >= 0")
    required_j = e_sun_j / config.eta_sun_path + e_eclipse_j / config.eta_recharge_path
    return required_j / t_sun_s


def required_array_power_design_w(raw_power_w: float, config: SolarArrayConfig) -> float:
    """Design (margined) required array electrical output, watts.

    ``P_SA,design = SF_P * P_SA,raw``
    """
    if raw_power_w < 0:
        raise ValueError(f"raw_power_w must be >= 0, got {raw_power_w!r}")
    return config.design_margin * raw_power_w


def required_array_area_m2(design_power_w: float, eol_density_w_m2_: float) -> float:
    """Required array area, m^2: ``A_SA = P_SA,design / p_usable,EOL``."""
    if design_power_w < 0:
        raise ValueError(f"design_power_w must be >= 0, got {design_power_w!r}")
    if eol_density_w_m2_ <= 0:
        raise ValueError(f"eol_density_w_m2_ must be > 0, got {eol_density_w_m2_!r}")
    return design_power_w / eol_density_w_m2_


@dataclass(frozen=True)
class EnergyClosureResult:
    """Independent verification that the sized array closes the orbit
    energy balance: raw-equivalent generation during sunlight must be
    >= the raw-equivalent requirement (sunlight loads + eclipse
    recharge, each expressed pre-loss).

    Attributes
    ----------
    generated_j:
        Raw electrical energy the *design*-power array produces over
        the sunlight arc: ``P_SA,design * t_sun_s``, joules.
    required_raw_j:
        Raw-equivalent energy required at unity margin:
        ``E_s / eta_s + E_e / eta_c``, joules.
    margin_fraction:
        ``generated_j / required_raw_j - 1``. By construction this
        equals ``design_margin - 1`` exactly (up to floating point),
        since ``generated_j = design_margin * required_raw_j``.
    closes:
        ``True`` iff ``generated_j >= required_raw_j``.
    """

    generated_j: float
    required_raw_j: float
    margin_fraction: float
    closes: bool


def verify_energy_closure(
    e_sun_j: float,
    e_eclipse_j: float,
    t_sun_s: float,
    design_power_w: float,
    config: SolarArrayConfig,
) -> EnergyClosureResult:
    """Independently verify orbit energy closure for a sized array.

    Recomputes the raw-equivalent requirement directly from
    ``e_sun_j``/``e_eclipse_j`` (not from a cached
    ``required_array_power_raw_w`` result) so this is a genuine
    independent check rather than a tautology.
    """
    if t_sun_s <= 0:
        raise ValueError(f"t_sun_s must be > 0, got {t_sun_s!r}")
    required_raw_j = (
        e_sun_j / config.eta_sun_path + e_eclipse_j / config.eta_recharge_path
    )
    generated_j = design_power_w * t_sun_s
    margin_fraction = (
        generated_j / required_raw_j - 1.0 if required_raw_j > 0 else float("inf")
    )
    return EnergyClosureResult(
        generated_j=generated_j,
        required_raw_j=required_raw_j,
        margin_fraction=margin_fraction,
        closes=generated_j >= required_raw_j,
    )


@dataclass(frozen=True)
class SolarArraySizingResult:
    """Full Milestone-2 solar-array sizing result for one orbit.

    Ties a Milestone-1 :class:`~power_budget.budget.PowerBudget`
    (reused, never recomputed) to a :class:`SolarArrayConfig` to
    produce the raw/design array power, BOL/EOL power density,
    required area, and an independent energy-closure check.
    """

    power_budget: "PowerBudget"
    config: SolarArrayConfig
    t_sun_s: float
    e_sun_j: float
    e_eclipse_j: float
    p_sa_raw_w: float
    p_sa_design_w: float
    bol_density_w_m2: float
    eol_density_w_m2: float
    area_m2: float
    closure: EnergyClosureResult

    @property
    def avg_power_w(self) -> float:
        """Orbit-average spacecraft power, watts (Milestone-1 value)."""
        return self.power_budget.orbit_average_power_w

    @property
    def raw_to_avg_ratio(self) -> float:
        """How much larger the raw array requirement is than naive P_avg sizing."""
        return self.p_sa_raw_w / self.avg_power_w

    def summary(self) -> str:
        c = self.closure
        return (
            f"Sunlight duration: {self.t_sun_s / 60:.1f} min\n"
            f"Sunlight load energy: {self.e_sun_j / 3600:.2f} Wh\n"
            f"Eclipse load energy (to be recharged): {self.e_eclipse_j / 3600:.2f} Wh\n"
            f"Naive avg-power estimate: {self.avg_power_w:.2f} W\n"
            f"Raw required array power: {self.p_sa_raw_w:.2f} W "
            f"({self.raw_to_avg_ratio:.2f}x naive avg power)\n"
            f"Design array power (SF_P={self.config.design_margin:.2f}): "
            f"{self.p_sa_design_w:.2f} W\n"
            f"BOL usable power density: {self.bol_density_w_m2:.1f} W/m^2\n"
            f"EOL usable power density: {self.eol_density_w_m2:.1f} W/m^2\n"
            f"Required array area: {self.area_m2:.3f} m^2\n"
            f"Energy closure: generated {c.generated_j / 3600:.2f} Wh vs "
            f"required {c.required_raw_j / 3600:.2f} Wh "
            f"(margin {c.margin_fraction * 100:.1f}%, closes={c.closes})"
        )


def size_solar_array(
    power_budget: "PowerBudget", config: SolarArrayConfig
) -> SolarArraySizingResult:
    """Compute the full Milestone-2 solar-array sizing from a Milestone-1
    :class:`~power_budget.budget.PowerBudget`.

    Reuses ``power_budget.phase_energy["sunlight"|"eclipse"]`` directly
    -- the spacecraft load model is never recreated here.
    """
    sun = power_budget.phase_energy["sunlight"]
    ecl = power_budget.phase_energy["eclipse"]

    t_sun_s = sun.duration_s
    e_sun_j = sun.energy_j
    e_eclipse_j = ecl.energy_j

    p_raw = required_array_power_raw_w(e_sun_j, e_eclipse_j, t_sun_s, config)
    p_design = required_array_power_design_w(p_raw, config)
    bol = bol_power_density_w_m2(config)
    eol = eol_power_density_w_m2(config)
    area = required_array_area_m2(p_design, eol)
    closure = verify_energy_closure(e_sun_j, e_eclipse_j, t_sun_s, p_design, config)

    return SolarArraySizingResult(
        power_budget=power_budget,
        config=config,
        t_sun_s=t_sun_s,
        e_sun_j=e_sun_j,
        e_eclipse_j=e_eclipse_j,
        p_sa_raw_w=p_raw,
        p_sa_design_w=p_design,
        bol_density_w_m2=bol,
        eol_density_w_m2=eol,
        area_m2=area,
        closure=closure,
    )
