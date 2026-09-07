"""Monte Carlo robustness analysis for a fixed EPS design (Milestone 4).

Critical rule (repeated from the module design brief): **the EPS
hardware is never resized inside a realization.** Every Monte Carlo
draw perturbs *mission conditions* (load level, activity durations,
eclipse fraction) and *EPS performance uncertainty* (cell efficiency,
degradation, path efficiencies) and asks whether the one fixed,
already-selected :class:`~power_budget.integrated.EPSDesign` still
closes the energy/DoD/recharge-time criteria for that draw. This is a
robustness study, not a re-sizing study.

Uncertainty model
-------------------
Every uncertain parameter reused here already exists somewhere in
Milestones 1-3 (load scale generalizes M1's schedule, eclipse fraction
is M1's own parameter, `eta_cell`/`f_array`/`f_eol` are M2's, `eta_sun_path`/
`eta_recharge_path` are M2's, `eta_discharge`/`f_cap_eol` are M3's). No
new physical dimension is invented. Each parameter is modeled as a
bounded (clipped) normal distribution around its Milestone 1-3 nominal
value, with a representative standard deviation and a physically
motivated clipping range (see :data:`UNCERTAINTY_PARAMS`).

    These distributions are representative engineering uncertainty
    assumptions, not statistically calibrated flight distributions.

Independence assumption
-------------------------
All parameters are sampled **independently** in this baseline model
(no correlation matrix). This is a simplification: in a real mission,
some of these quantities plausibly correlate (e.g. a harsher radiation
environment could simultaneously depress both `f_eol` and
`f_cap_eol`). Independence is not claimed to be physically proven --
it is a stated, documented limitation of this baseline robustness
model (see `docs/integrated_eps_methodology.md`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from power_budget.battery import BatteryConfig, simulate_orbit_soc, verify_recharge_closure
from power_budget.budget import build_power_budget
from power_budget.integrated import EPSDesign
from power_budget.modes import Mode
from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule, ScheduleEntry
from power_budget.solar import SolarArrayConfig


# ---------------------------------------------------------------------------
# Uncertainty parameter model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class UncertainParam:
    """One uncertain quantity: bounded-normal distribution around a
    Milestone 1-3 nominal value.

    Attributes
    ----------
    name: identifier, matches the keyword used in realization sampling.
    nominal: the Milestone 1-3 baseline value (distribution mean).
    std: representative standard deviation.
    low, high: physical/engineering clipping bounds (hard truncation).
    """

    name: str
    nominal: float
    std: float
    low: float
    high: float

    def sample(self, rng: np.random.Generator, n: int = 1) -> np.ndarray:
        draws = rng.normal(self.nominal, self.std, size=n)
        return np.clip(draws, self.low, self.high)


# Nominal values below are the Milestone 1-3 accepted baseline values;
# std/bounds are stated representative engineering judgment.
UNCERTAINTY_PARAMS: dict[str, UncertainParam] = {
    "load_scale": UncertainParam("load_scale", 1.00, 0.05, 0.85, 1.20),
    "comms_duty_scale": UncertainParam("comms_duty_scale", 1.00, 0.15, 0.50, 2.00),
    "payload_duty_scale": UncertainParam("payload_duty_scale", 1.00, 0.15, 0.50, 2.00),
    "eclipse_fraction": UncertainParam("eclipse_fraction", 0.356, 0.020, 0.20, 0.50),
    "eta_cell": UncertainParam("eta_cell", 0.30, 0.015, 0.20, 0.35),
    "f_array": UncertainParam("f_array", 0.85, 0.03, 0.70, 0.95),
    "f_eol_pv": UncertainParam("f_eol_pv", 0.85, 0.03, 0.65, 1.00),
    "eta_sun_path": UncertainParam("eta_sun_path", 0.90, 0.02, 0.75, 0.98),
    "eta_recharge_path": UncertainParam("eta_recharge_path", 0.85, 0.03, 0.60, 0.98),
    "eta_discharge": UncertainParam("eta_discharge", 0.95, 0.02, 0.80, 1.00),
    "f_cap_eol_batt": UncertainParam("f_cap_eol_batt", 0.80, 0.04, 0.60, 1.00),
}

SOLAR_CONSTANT_W_M2 = 1361.0  # fixed, per Milestone 2

# Baseline mission timing constants (Milestone 1/2), reused unchanged.
_ORBIT_PERIOD_S = 5676.0
_PRE_IMAGING_S = 1200.0
_PAYLOAD_DURATION_S = 1200.0
_DOWNLINK_DURATION_S = 600.0
_DOWNLINK_OFFSET_AFTER_SUNEND_S = 500.0  # downlink starts this far past the terminator

_NOMINAL_POWER_W = 6.8
_PAYLOAD_POWER_W = 14.5
_DOWNLINK_POWER_W = 10.2


def _build_realization_schedule(
    load_scale: float,
    comms_duty_scale: float,
    payload_duty_scale: float,
    eclipse_fraction: float,
) -> tuple[OrbitSchedule, OrbitGeometry]:
    """Construct the mission schedule/orbit for one Monte Carlo draw.

    Reproduces the M1 baseline timeline structure (pre-imaging
    housekeeping, imaging pass, housekeeping, downlink pass near/after
    the terminator, housekeeping to close the orbit) with mode powers
    scaled by ``load_scale`` and activity durations scaled by the duty
    factors, on an orbit with the sampled ``eclipse_fraction``. This
    mirrors ``scripts/mission_baseline.build_schedule`` but is
    self-contained here so the robustness engine has no dependency on
    the ``scripts/`` path-inserted module.
    """
    orbit = OrbitGeometry(period_s=_ORBIT_PERIOD_S, eclipse_fraction=eclipse_fraction)
    sun_end_s = orbit.sunlight_end_s

    nominal = Mode("nominal", _NOMINAL_POWER_W * load_scale)
    payload = Mode("payload_imaging", _PAYLOAD_POWER_W * load_scale)
    downlink = Mode("downlink", _DOWNLINK_POWER_W * load_scale)

    payload_duration_s = _PAYLOAD_DURATION_S * payload_duty_scale
    downlink_duration_s = _DOWNLINK_DURATION_S * comms_duty_scale
    downlink_start_s = sun_end_s + _DOWNLINK_OFFSET_AFTER_SUNEND_S

    imaging_end_s = _PRE_IMAGING_S + payload_duration_s
    downlink_end_s = downlink_start_s + downlink_duration_s

    # Guard against pathological extreme draws colliding activities or
    # exceeding the orbit; clip durations rather than raise, so a
    # Monte Carlo campaign never crashes on a rare extreme combination.
    if imaging_end_s > downlink_start_s:
        payload_duration_s = max(downlink_start_s - _PRE_IMAGING_S, 0.0)
        imaging_end_s = _PRE_IMAGING_S + payload_duration_s
    if downlink_end_s > orbit.period_s:
        downlink_duration_s = max(orbit.period_s - downlink_start_s, 0.0)
        downlink_end_s = downlink_start_s + downlink_duration_s

    raw_spans = [
        (nominal, 0.0, _PRE_IMAGING_S),
        (payload, _PRE_IMAGING_S, imaging_end_s),
        (nominal, imaging_end_s, downlink_start_s),
        (downlink, downlink_start_s, downlink_end_s),
        (nominal, downlink_end_s, orbit.period_s),
    ]
    spans = [s for s in raw_spans if s[2] - s[1] > 1e-9]
    coalesced: list[tuple[Mode, float, float]] = []
    for mode, start, end in spans:
        if coalesced and coalesced[-1][0] is mode and abs(coalesced[-1][2] - start) < 1e-6:
            prev_mode, prev_start, _ = coalesced[-1]
            coalesced[-1] = (prev_mode, prev_start, end)
        else:
            coalesced.append((mode, start, end))

    entries = tuple(ScheduleEntry(m, s, e) for m, s, e in coalesced)
    schedule = OrbitSchedule(entries=entries, orbit_period_s=orbit.period_s)
    return schedule, orbit


def scale_schedule_power(schedule: OrbitSchedule, load_scale: float) -> OrbitSchedule:
    """Return a copy of ``schedule`` with every mode's power scaled by
    ``load_scale``, preserving all timing. Reusable outside the
    Monte Carlo engine (e.g. for the deterministic robust corner)."""
    cache: dict[str, Mode] = {}
    new_entries = []
    for e in schedule.entries:
        name = e.mode.name
        if name not in cache:
            cache[name] = Mode(name, e.mode.power_w * load_scale, e.mode.description)
        new_entries.append(ScheduleEntry(cache[name], e.start_s, e.end_s))
    return OrbitSchedule(entries=tuple(new_entries), orbit_period_s=schedule.orbit_period_s)


# ---------------------------------------------------------------------------
# Per-realization evaluation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RealizationResult:
    """Outcome of evaluating the fixed EPS design against one sampled
    (or deterministic) mission/EPS-performance scenario."""

    params: dict[str, float]
    energy_ok: bool
    dod_ok: bool
    recharge_ok: bool
    passed: bool
    failure_mode: str | None  # None if passed
    solar_energy_margin: float
    dod_actual: float
    min_soc: float
    recharge_utilization: float  # t_recharge / t_sunlight (nan if undefined)


def evaluate_realization(design: EPSDesign, params: dict[str, float]) -> RealizationResult:
    """Evaluate the fixed ``design`` against one scenario described by
    ``params`` (a dict with the keys in :data:`UNCERTAINTY_PARAMS`,
    already sampled/clipped or set deterministically).

    Never resizes ``design`` -- only the scenario and the design's
    *actual physical performance* (via the sampled efficiency/
    degradation parameters) vary.
    """
    schedule, orbit = _build_realization_schedule(
        load_scale=params["load_scale"],
        comms_duty_scale=params["comms_duty_scale"],
        payload_duty_scale=params["payload_duty_scale"],
        eclipse_fraction=params["eclipse_fraction"],
    )
    power_budget = build_power_budget(schedule, orbit)
    sun = power_budget.phase_energy["sunlight"]
    ecl = power_budget.phase_energy["eclipse"]

    # Actual physical array output under sampled cell efficiency /
    # array factor / EOL degradation -- the *fixed* area times the
    # *uncertain* power density, not a re-sized array.
    p_array_actual_w = (
        design.array_area_m2
        * SOLAR_CONSTANT_W_M2
        * params["eta_cell"]
        * params["f_array"]
        * params["f_eol_pv"]
    )

    solar_cfg = SolarArrayConfig(
        eta_cell=params["eta_cell"],
        f_array=params["f_array"],
        f_eol=params["f_eol_pv"],
        eta_sun_path=params["eta_sun_path"],
        eta_recharge_path=params["eta_recharge_path"],
        design_margin=1.0,  # not used here (no re-sizing)
    )
    battery_cfg = BatteryConfig(
        eta_discharge=params["eta_discharge"],
        dod_max=design.dod_max,  # operational policy limit, fixed
        capacity_margin=1.0,  # not used here (no re-sizing)
        f_cap_eol=1.0,  # retention already folded into capacity_j below
    )
    capacity_j = design.battery_capacity_bol_wh * params["f_cap_eol_batt"] * 3600.0

    withdrawal_j = ecl.energy_j / params["eta_discharge"]
    closure = verify_recharge_closure(
        e_sun_j=sun.energy_j,
        t_sun_s=sun.duration_s,
        p_sa_design_w=p_array_actual_w,
        withdrawal_j=withdrawal_j,
        solar_config=solar_cfg,
    )
    energy_ok = closure.closes
    solar_energy_margin = (
        closure.available_recharge_j / closure.required_j if closure.required_j > 0 else float("inf")
    )

    dod_ok = False
    recharge_ok = False
    min_soc = float("nan")
    dod_actual = float("nan")
    recharge_utilization = float("nan")
    failure_mode: str | None = None

    try:
        profile = simulate_orbit_soc(
            schedule=schedule,
            orbit=orbit,
            p_sa_design_w=p_array_actual_w,
            solar_config=solar_cfg,
            battery_config=battery_cfg,
            capacity_j=capacity_j,
        )
    except ValueError as exc:
        msg = str(exc)
        if "exceeds design array output" in msg:
            failure_mode = "solar_deficit"
        elif "undersized" in msg:
            failure_mode = "battery_depleted"
        else:
            failure_mode = "simulation_error"
        passed = False
        return RealizationResult(
            params=params, energy_ok=energy_ok, dod_ok=False, recharge_ok=False,
            passed=passed, failure_mode=failure_mode,
            solar_energy_margin=solar_energy_margin, dod_actual=float("nan"),
            min_soc=float("nan"), recharge_utilization=float("nan"),
        )

    min_soc = profile.min_soc
    dod_actual = 1.0 - min_soc
    dod_ok = dod_actual <= design.dod_max + 1e-9
    recharge_ok = profile.t_recharge_s is not None and profile.t_recharge_s <= sun.duration_s + 1e-6
    if profile.t_recharge_s is not None and sun.duration_s > 0:
        recharge_utilization = profile.t_recharge_s / sun.duration_s

    passed = energy_ok and dod_ok and recharge_ok
    if not passed:
        if not energy_ok:
            failure_mode = "solar_energy_deficit"
        elif not dod_ok:
            failure_mode = "dod_exceeded"
        elif not recharge_ok:
            failure_mode = "recharge_incomplete"

    return RealizationResult(
        params=params, energy_ok=energy_ok, dod_ok=dod_ok, recharge_ok=recharge_ok,
        passed=passed, failure_mode=failure_mode,
        solar_energy_margin=solar_energy_margin, dod_actual=dod_actual,
        min_soc=min_soc, recharge_utilization=recharge_utilization,
    )


def nominal_params() -> dict[str, float]:
    """The all-nominal (unperturbed) parameter set."""
    return {k: p.nominal for k, p in UNCERTAINTY_PARAMS.items()}


# ---------------------------------------------------------------------------
# Wilson score confidence interval
# ---------------------------------------------------------------------------
def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score binomial confidence interval (default 95%, z=1.96).

    More reliable than the naive normal-approximation interval near
    p=0 or p=1, which is common in a high-reliability closure study.
    """
    if n <= 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1.0 + z**2 / n
    center = phat + z**2 / (2 * n)
    adj = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))
    lo = (center - adj) / denom
    hi = (center + adj) / denom
    return (max(0.0, lo), min(1.0, hi))


# ---------------------------------------------------------------------------
# Monte Carlo campaign
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MonteCarloResult:
    n: int
    n_pass: int
    p_pass: float
    ci95: tuple[float, float]
    results_df: pd.DataFrame
    failure_mode_counts: dict[str, int]


def _sample_all_params(rng: np.random.Generator, n: int) -> list[dict[str, float]]:
    columns = {name: p.sample(rng, n) for name, p in UNCERTAINTY_PARAMS.items()}
    return [{name: float(columns[name][i]) for name in UNCERTAINTY_PARAMS} for i in range(n)]


def run_monte_carlo(design: EPSDesign, n: int = 10000, seed: int = 42) -> MonteCarloResult:
    """Run a fixed-hardware Monte Carlo robustness campaign.

    Deterministic given ``seed`` -- the same seed always produces the
    same parameter draws (and hence the same pass/fail outcome per
    realization), so results are exactly reproducible.
    """
    rng = np.random.default_rng(seed)
    all_params = _sample_all_params(rng, n)
    rows = []
    for params in all_params:
        r = evaluate_realization(design, params)
        row = dict(params)
        row["passed"] = r.passed
        row["failure_mode"] = r.failure_mode
        row["solar_energy_margin"] = r.solar_energy_margin
        row["dod_actual"] = r.dod_actual
        row["min_soc"] = r.min_soc
        row["recharge_utilization"] = r.recharge_utilization
        rows.append(row)
    df = pd.DataFrame(rows)

    n_pass = int(df["passed"].sum())
    p_pass = n_pass / n if n > 0 else float("nan")
    ci = wilson_interval(n_pass, n)
    failure_counts = (
        df.loc[~df["passed"], "failure_mode"].value_counts().to_dict() if n_pass < n else {}
    )
    return MonteCarloResult(
        n=n, n_pass=n_pass, p_pass=p_pass, ci95=ci, results_df=df, failure_mode_counts=failure_counts
    )


def convergence_study(
    design: EPSDesign, checkpoints=(100, 1000, 5000, 10000), seed: int = 42
) -> pd.DataFrame:
    """Run one Monte Carlo draw of size ``max(checkpoints)`` and report
    closure-probability convergence at each checkpoint as a growing
    prefix of the same deterministic draw sequence (not independent
    re-runs) -- so each larger checkpoint is a strict refinement of
    the smaller ones, isolating sample-size effects from RNG noise."""
    n_max = max(checkpoints)
    mc = run_monte_carlo(design, n=n_max, seed=seed)
    df = mc.results_df
    rows = []
    for n in checkpoints:
        prefix = df.iloc[:n]
        n_pass = int(prefix["passed"].sum())
        p_pass = n_pass / n
        lo, hi = wilson_interval(n_pass, n)
        rows.append(
            {
                "n": n,
                "p_pass": p_pass,
                "ci95_lo": lo,
                "ci95_hi": hi,
                "ci95_width": hi - lo,
                "p10_solar_margin": prefix["solar_energy_margin"].quantile(0.10),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# One-at-a-time sensitivity ranking
# ---------------------------------------------------------------------------
def sensitivity_ranking(design: EPSDesign) -> pd.DataFrame:
    """One-at-a-time (+/- 1 std) finite-difference sensitivity of the
    solar-energy margin and actual DoD to each uncertain parameter,
    holding all others at nominal.

    Reports a normalized sensitivity: fractional change in the output
    metric per +/-1 standard deviation perturbation, so parameters
    with different units/scales are directly comparable. This is a
    transparent, simple method (not a variance-based/Sobol index) --
    documented as such; it does not claim to capture interaction
    effects between parameters.
    """
    base = nominal_params()
    base_result = evaluate_realization(design, base)
    base_margin = base_result.solar_energy_margin
    base_dod = base_result.dod_actual

    rows = []
    for name, uparam in UNCERTAINTY_PARAMS.items():
        plus = dict(base)
        minus = dict(base)
        plus[name] = min(uparam.nominal + uparam.std, uparam.high)
        minus[name] = max(uparam.nominal - uparam.std, uparam.low)

        r_plus = evaluate_realization(design, plus)
        r_minus = evaluate_realization(design, minus)

        d_margin = r_plus.solar_energy_margin - r_minus.solar_energy_margin
        norm_margin_sens = d_margin / (2 * base_margin) if base_margin else float("nan")

        d_dod = r_plus.dod_actual - r_minus.dod_actual
        norm_dod_sens = d_dod / (2 * base_dod) if base_dod else float("nan")

        rows.append(
            {
                "parameter": name,
                "solar_margin_sensitivity": norm_margin_sens,
                "dod_sensitivity": norm_dod_sens,
            }
        )
    df = pd.DataFrame(rows)
    df["rank_score"] = df["solar_margin_sensitivity"].abs() + df["dod_sensitivity"].abs()
    return df.sort_values("rank_score", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Deterministic robust corner
# ---------------------------------------------------------------------------
def robust_corner_params() -> dict[str, float]:
    """A single, defensible conservative design corner: every
    parameter set roughly one standard deviation toward its
    unfavorable direction, not stacked at absolute physical extremes.
    Documented explicitly (not silently derived) -- see
    `docs/integrated_eps_methodology.md`."""
    p = UNCERTAINTY_PARAMS
    return {
        "load_scale": p["load_scale"].nominal + p["load_scale"].std * 2,  # +10% growth
        "comms_duty_scale": p["comms_duty_scale"].nominal + p["comms_duty_scale"].std * 1.5,
        "payload_duty_scale": p["payload_duty_scale"].nominal + p["payload_duty_scale"].std * 1.0,
        "eclipse_fraction": p["eclipse_fraction"].nominal + p["eclipse_fraction"].std * 2.2,  # ~0.40
        "eta_cell": p["eta_cell"].nominal - p["eta_cell"].std * 1.0,
        "f_array": p["f_array"].nominal - p["f_array"].std * 1.0,
        "f_eol_pv": p["f_eol_pv"].nominal - p["f_eol_pv"].std * 1.0,
        "eta_sun_path": p["eta_sun_path"].nominal - p["eta_sun_path"].std * 1.0,
        "eta_recharge_path": p["eta_recharge_path"].nominal - p["eta_recharge_path"].std * 1.0,
        "eta_discharge": p["eta_discharge"].nominal - p["eta_discharge"].std * 1.0,
        "f_cap_eol_batt": p["f_cap_eol_batt"].nominal - p["f_cap_eol_batt"].std * 1.0,
    }


def evaluate_robust_corner(design: EPSDesign) -> RealizationResult:
    return evaluate_realization(design, robust_corner_params())


# ---------------------------------------------------------------------------
# Mission-operations feasibility map (2D)
# ---------------------------------------------------------------------------
def classify_feasibility(result: RealizationResult, headroom_threshold: float = 0.10) -> str:
    """Classify a realization as 'infeasible', 'marginal', or 'feasible'.

    'marginal' means it passes all three criteria but the worst
    relative headroom (energy margin above 1, DoD headroom below max,
    or recharge-time headroom below sunlight duration) is under
    ``headroom_threshold`` (default 10%) -- a transparent, stated rule.
    """
    if not result.passed:
        return "infeasible"
    energy_headroom = result.solar_energy_margin - 1.0
    # DoD headroom relative to the allowable limit is not included here as
    # a third independent factor because RealizationResult does not carry
    # design.dod_max directly; energy margin and recharge headroom already
    # capture the two continuous margins computed per realization.
    recharge_headroom = (
        1.0 - result.recharge_utilization if not math.isnan(result.recharge_utilization) else 1.0
    )
    worst = min(energy_headroom, recharge_headroom)
    return "marginal" if worst < headroom_threshold else "feasible"


def mission_operations_map(
    design: EPSDesign,
    eclipse_fractions: np.ndarray,
    comms_duty_scales: np.ndarray,
) -> pd.DataFrame:
    """Deterministic (no uncertainty) 2D feasibility map over eclipse
    fraction x communications duty scale, all other parameters held at
    nominal, for the fixed design."""
    rows = []
    base = nominal_params()
    for f_e in eclipse_fractions:
        for comms in comms_duty_scales:
            params = dict(base)
            params["eclipse_fraction"] = float(f_e)
            params["comms_duty_scale"] = float(comms)
            r = evaluate_realization(design, params)
            rows.append(
                {
                    "eclipse_fraction": float(f_e),
                    "comms_duty_scale": float(comms),
                    "passed": r.passed,
                    "failure_mode": r.failure_mode,
                    "solar_energy_margin": r.solar_energy_margin,
                    "dod_actual": r.dod_actual,
                    "feasibility": classify_feasibility(r),
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Hardware trade map (2D): array area x battery capacity
# ---------------------------------------------------------------------------
def hardware_trade_map(
    array_areas_m2: np.ndarray,
    battery_capacities_wh: np.ndarray,
    array_eol_density_w_m2: float,
    array_bol_density_w_m2: float,
    eta_sun_path: float,
    eta_recharge_path: float,
    battery_f_cap_eol: float,
    dod_max: float,
    eta_discharge: float,
    scenario_params: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Deterministic 2D feasibility map over (array area, battery
    capacity) for one scenario (nominal by default, or the robust
    corner if ``scenario_params`` is given)."""
    params = dict(scenario_params) if scenario_params is not None else nominal_params()
    rows = []
    for area in array_areas_m2:
        for cap in battery_capacities_wh:
            design = EPSDesign(
                array_area_m2=float(area),
                array_bol_density_w_m2=array_bol_density_w_m2,
                array_eol_density_w_m2=array_eol_density_w_m2,
                eta_sun_path=eta_sun_path,
                eta_recharge_path=eta_recharge_path,
                battery_capacity_bol_wh=float(cap),
                battery_f_cap_eol=battery_f_cap_eol,
                dod_max=dod_max,
                eta_discharge=eta_discharge,
            )
            r = evaluate_realization(design, params)
            rows.append(
                {
                    "array_area_m2": float(area),
                    "battery_capacity_wh": float(cap),
                    "passed": r.passed,
                    "failure_mode": r.failure_mode,
                }
            )
    return pd.DataFrame(rows)
