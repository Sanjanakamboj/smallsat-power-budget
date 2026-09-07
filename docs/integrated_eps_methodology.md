# Methodology — Milestone 4: Integrated EPS Robustness, Margin Rollup & Final Sizing

This document defines the integration, robustness, and final-sizing
methodology in `src/power_budget/integrated.py` and
`src/power_budget/robustness.py`, used by
`scripts/final_eps_study.py`. It builds on Milestones 1-3
(`docs/methodology.md`, `docs/solar_array_methodology.md`,
`docs/battery_sizing_methodology.md`) without modifying any of them.

## 1. Scope

Milestone 4 answers:

> Does the selected solar-array/battery design remain adequate when
> realistic mission-growth and modeling uncertainties occur together,
> and which assumptions actually control EPS robustness?

It is the capstone integration milestone: no new electrical hardware
physics is introduced. Every uncertain parameter reused here already
exists somewhere in M1-M3 (§7).

## 2. Requirement vs. capability

`integrated.py` separates two concepts kept implicit in earlier
milestones:

- **`MissionRequirement`**: what a specific mission scenario (a
  schedule + orbit, via M1's `PowerBudget`) demands — sunlight/eclipse
  energy, peak load, orbit energy.
- **`EPSDesign`**: the *fixed*, selected hardware and the
  representative assumptions describing how it performs — array area
  and BOL/EOL power density, battery BOL nameplate capacity and EOL
  retention, and the M2/M3 path efficiencies. `EPSDesign` never
  resizes itself.

Margins compare a requirement against a design's capability for one
scenario; four are computed explicitly and never collapsed into one
number (`integrated.compute_margins`):

```
M_E = E_available,sun,EOL / E_required,sun+recharge      (solar energy margin)
M_P = P_array,EOL / P_array,required,raw                  (array power margin)
M_B = DoD_max * C_available,EOL / E_batt,withdrawal        (battery energy margin)
M_R = t_sunlight / t_recharge                               (recharge-time margin)
```

## 3. Avoiding double-counting

M2's `design_margin` (25%) and M3's `capacity_margin` (25%) are baked
into the *selected* array area and battery capacity exactly once, at
selection time (Milestones 2 and 3). Milestone 4:

- computes nominal margins (§2) by comparing the *already-margined*
  selected design's EOL capability against the *raw, unmargined*
  requirement — reproducing, as a consistency check, M2's own +25%
  design margin exactly at the M2/M3-selected design point (verified
  in `tests/test_integrated.py::test_compute_margins_matches_m2_at_nominal_design`);
- in the Monte Carlo/robust-corner evaluation (§6), constructs
  `SolarArrayConfig`/`BatteryConfig` instances with `design_margin=1.0`
  / `capacity_margin=1.0` explicitly, so the sizing-time safety factor
  is never reapplied inside a robustness realization — only the
  design's fixed, already-margined area/capacity and the scenario's
  actual (possibly degraded) physical performance parameters determine
  the outcome.

## 4. Reconciling the analytical minimum vs. the selected design

M2's continuous analytical minimum array area is **0.0654 m²**; M3's
analytical minimum BOL battery capacity, after M3's own 5 Wh rounding
rule, is **30.0 Wh**. Milestone 4 tests this `minimum_design` (built
directly from the accepted M2/M3 results via
`integrated.eps_design_from_baseline`) against one deterministic robust
corner (§5) — it fails, on two independent criteria (§9) — and
escalates only the capabilities shown to be inadequate, to a **final
selected design of 0.085 m² / 35 Wh** (§9). The escalation:

- Array area: rounded to the nearest 0.005 m² above the corner's own
  minimum-sufficient area (~0.078 m²) plus headroom — a modest,
  stated increment (not an arbitrary choice; see §9's derivation
  table, `results/m4_escalation_derivation.csv`).
- Battery capacity: rounded to the nearest 5 Wh (the same rounding
  granularity M3 already established) above the corner's own
  minimum-sufficient capacity (~32 Wh).

Neither is escalated further than the robust corner demonstrably
requires; upstream assumptions were never adjusted to make this
requirement smaller (per the milestone brief's explicit prohibition).

## 5. Uncertainty variables

Every parameter in `robustness.UNCERTAINTY_PARAMS` already exists in
M1-M3 -- no new physical dimension is invented.

| Parameter | M1-M3 origin | Nominal | Std | Bounds |
|---|---|---:|---:|---|
| `load_scale` | scales every M1 mode power | 1.00 | 0.05 | [0.85, 1.20] |
| `comms_duty_scale` | scales M1/M2 downlink duration | 1.00 | 0.15 | [0.50, 2.00] |
| `payload_duty_scale` | scales M1/M2 payload duration | 1.00 | 0.15 | [0.50, 2.00] |
| `eclipse_fraction` | M1 `OrbitGeometry.eclipse_fraction` | 0.356 | 0.020 | [0.20, 0.50] |
| `eta_cell` | M2 `SolarArrayConfig.eta_cell` | 0.30 | 0.015 | [0.20, 0.35] |
| `f_array` | M2 `SolarArrayConfig.f_array` | 0.85 | 0.03 | [0.70, 0.95] |
| `f_eol_pv` | M2 `SolarArrayConfig.f_eol` | 0.85 | 0.03 | [0.65, 1.00] |
| `eta_sun_path` | M2 `SolarArrayConfig.eta_sun_path` | 0.90 | 0.02 | [0.75, 0.98] |
| `eta_recharge_path` | M2 `SolarArrayConfig.eta_recharge_path` | 0.85 | 0.03 | [0.60, 0.98] |
| `eta_discharge` | M3 `BatteryConfig.eta_discharge` | 0.95 | 0.02 | [0.80, 1.00] |
| `f_cap_eol_batt` | M3 `BatteryConfig.f_cap_eol` | 0.80 | 0.04 | [0.60, 1.00] |

`dod_max` (M3's operational policy limit, 0.25) is **not** sampled —
it is the fixed pass/fail threshold checked against the actual DoD
each realization produces.

Each parameter is modeled as a bounded (hard-clipped) normal
distribution: `numpy.random.Generator.normal(nominal, std)` clipped to
`[low, high]`.

> These distributions are representative engineering uncertainty
> assumptions, not statistically calibrated flight distributions.

## 6. Independence assumption

All eleven parameters are sampled **independently** — no correlation
structure is modeled. This is a stated simplification, not a claim of
physical proof: real spacecraft environments plausibly correlate some
of these (e.g. a harsher-than-expected radiation environment could
depress both `f_eol_pv` and `f_cap_eol_batt` together). A correlated
model is a natural extension, out of scope here.

## 7. Monte Carlo engine — the critical rule

`robustness.run_monte_carlo()` draws `N` independent parameter sets
and, **for each one**, evaluates the one *fixed* `EPSDesign` — the
hardware is never resized inside a realization
(`tests/test_robustness.py::test_evaluate_realization_does_not_mutate_design`
and the `test_monte_carlo_never_resizes_hardware` regression). Per
realization (`robustness.evaluate_realization`):

1. build the scenario's schedule/orbit from the sampled mission
   parameters (`load_scale`, `comms_duty_scale`, `payload_duty_scale`,
   `eclipse_fraction`);
2. compute `E_s`, `E_e`, `t_sun` via M1's `build_power_budget`;
3. compute the *actual physical* array output under sampled
   `eta_cell`/`f_array`/`f_eol_pv` at the design's *fixed* area (never
   the design's nominal design power);
4. check energy closure via M3's own `verify_recharge_closure` (the
   same function M3 uses for its own M2↔M3 consistency check),
   comparing available sunlight surplus against the battery-side
   withdrawal;
5. run M3's own `simulate_orbit_soc` with the sampled path/discharge
   efficiencies and the design's fixed capacity (scaled by sampled
   `f_cap_eol_batt`) to get the actual minimum SOC and recharge time;
6. classify pass/fail against the three criteria (§8).

No new physics is written for this step — it reuses M2's
`verify_recharge_closure`... (M3's, precisely) and M3's
`simulate_orbit_soc` directly.

## 8. Closure criteria and failure modes

A realization passes only if **all three** hold:

```
E_available >= E_required          (checked via M3's verify_recharge_closure)
DoD_actual  <= DoD_max              (checked via 1 - simulate_orbit_soc's min_soc)
t_recharge  <= t_sunlight            (checked via simulate_orbit_soc's t_recharge_s)
```

Failure modes are individually tagged, not collapsed into one boolean:
`solar_deficit` (the array's raw output cannot even cover
instantaneous sunlight-phase load -- a hard model violation raised by
`simulate_orbit_soc`), `battery_depleted` (the battery would go
negative during eclipse), `solar_energy_deficit` (energy criterion
fails), `dod_exceeded`, `recharge_incomplete`. This lets the campaign
report *which* criterion dominates failures, not just how many
realizations failed.

## 9. Baseline Monte Carlo campaign (final design)

`N = 10,000`, `seed = 42` (deterministic — `run_monte_carlo` with the
same seed always reproduces the same draws and outcomes,
`tests/test_robustness.py::test_monte_carlo_deterministic_with_seed`).

| Result | Value |
|---|---:|
| Closure probability | **99.99%** |
| 95% Wilson CI | **[99.94%, 100.00%]** |
| Dominant failure mode | `solar_energy_deficit` (1 of 1 failures) |
| Median solar recharge margin | ≈2.7x |
| Median minimum SOC | ≈84% |
| Median recharge utilization | ≈30% of sunlight |

The confidence interval uses the **Wilson score interval**
(`robustness.wilson_interval`), which stays well-behaved near `p≈1`
(unlike the naive normal approximation, which can produce an upper
bound above 1 or an artificially narrow interval near a boundary).

## 10. Monte Carlo convergence

`robustness.convergence_study` draws one `N=10,000` sequence and
reports closure probability at growing prefixes
(`N=100,1000,5000,10000`) of that *same* sequence — isolating
sample-size effects from RNG noise (a fresh independent draw at each
`N` would conflate the two). The 95% CI half-width narrows from ~3.7%
at `N=100` to ~0.05% at `N=10,000`, and the estimated closure
probability is stable (100.0% → 100.0% → 100.0% → 99.99%) across all
four checkpoints — the campaign has converged well before `N=10,000`.

## 11. Deterministic robust corner

One explicit, defensible conservative scenario
(`robustness.robust_corner_params`): each parameter shifted roughly
1-2 standard deviations toward its unfavorable direction (load +2σ,
comms duty +1.5σ, payload duty +1σ, eclipse fraction +2.2σ ≈ 0.40; PV
cell efficiency, array factor, EOL PV degradation, both path
efficiencies, discharge efficiency, and EOL battery retention each
-1σ) — **not** every variable stacked at its absolute physical
extreme, which the milestone brief explicitly warned against. Every
corner value is verified to lie within its parameter's stated
uncertainty bounds
(`tests/test_robustness.py::test_robust_corner_within_uncertainty_bounds`).

- **M2/M3 analytical-minimum design (0.0654 m² / 30 Wh) at this
  corner: FAILS**, with `failure_mode = "solar_deficit"` — the array's
  raw electrical output at the corner's degraded cell
  efficiency/array factor/EOL degradation cannot even cover the
  sunlight-phase payload-imaging load.
- Escalating **array area alone** (to 0.085 m², battery unchanged at
  30 Wh) removes the solar deficit but the corner **still fails**,
  now with `failure_mode = "dod_exceeded"` (actual DoD ≈25.8% >
  `DoD_max` = 25%) — the battery alone was independently inadequate.
- Escalating **battery alone** (to 35 Wh, array unchanged at
  0.0654 m²) leaves the corner failing with `solar_deficit` — the
  array alone was independently inadequate.
- The **final design (0.085 m² / 35 Wh) passes** the robust corner
  with margin (solar recharge margin 1.29x, actual DoD 22.2% <
  25% limit).

Both escalations were genuinely, independently necessary — confirmed
by `tests/test_m4_script.py::test_array_only_escalation_insufficient_for_dod`
and `test_battery_only_escalation_insufficient_for_solar`.

## 12. Sensitivity ranking

`robustness.sensitivity_ranking` uses a one-at-a-time (±1 standard
deviation) finite-difference method, holding all other parameters at
nominal, reporting the *normalized* (fractional-change-per-1σ)
sensitivity of the solar recharge margin and the actual DoD to each
parameter. This is a transparent, simple method — it does **not**
claim to capture interaction effects between parameters (a full
variance-based/Sobol decomposition would; that is out of scope here).

Top-ranked drivers (final design):

1. **Spacecraft load level** and **eclipse fraction** (roughly tied,
   ~8.5-8.6% swing in solar margin per 1σ) — the two mission-side
   drivers dominate.
2. **PV cell efficiency** (~8.5%) — the strongest single array-
   technology driver.
3. **Array EOL degradation** and **array packing/incidence factor**
   (~6.0% each).
4. **Battery EOL capacity retention** (~5.0% swing in DoD) — the
   dominant battery-specific driver.

## 13. Solar vs. battery drivers

Consistent with M2/M3's own findings, the sensitivity ranking (§12)
and the hardware trade map (§15) confirm:

- **Array-sizing drivers**: eclipse fraction, load level, cell
  efficiency, EOL PV degradation, array packing/incidence factor,
  charge-path efficiency — the same set M2 identified.
- **Battery-sizing drivers**: eclipse fraction, load level (both
  through eclipse energy), EOL battery capacity retention, discharge
  efficiency, and — as M3's timing experiment showed — *when* a
  high-power activity occurs (in eclipse vs. sunlight), not just
  total duty cycle.

## 14. Mission operating envelope

`robustness.mission_operations_map` sweeps eclipse fraction
(0.20-0.50) against communications duty scale (0.5x-4.5x baseline),
all else nominal, classifying each cell `feasible` / `marginal` /
`infeasible` (marginal: passes but worst headroom <10%, a stated,
transparent rule in `robustness.classify_feasibility`). For the final
design, the entire baseline-representative region (eclipse fraction up
to ~0.46 at any communications duty, or communications duty up to
~2.3x at any eclipse fraction up to 0.50) is feasible; infeasibility
only appears in the corner of very high eclipse fraction (>~0.46)
*combined with* very high communications duty (>~2.3x baseline) — a
combined stress the baseline mission is nowhere near.

## 15. Hardware trade map

`robustness.hardware_trade_map` sweeps array area (0.04-0.11 m²)
against battery capacity (15-45 Wh) under nominal conditions and under
the robust corner, producing the strongest portfolio figure
(`results/figures/m4_hardware_trade.png`): the M2/M3 analytical
minimum sits inside the feasible region under nominal conditions but
falls into the infeasible region under the robust corner; the final
selected design sits inside the feasible region under **both**.

## 16. Final recommendation

| | Analytical minimum | Final selected |
|---|---:|---:|
| Array area | 0.0654 m² | **0.085 m²** |
| Array EOL output | 19.30 W | **25.07 W** |
| Battery BOL capacity | 30.0 Wh | **35.0 Wh** |
| Battery EOL capacity | 24.0 Wh | **28.0 Wh** |
| Robust corner | FAIL | **PASS** |
| Monte Carlo closure | (not applicable to unmargined design) | **99.99%** |

The final recommendation is **0.085 m² array / 35 Wh battery** — a
modest, quantitatively-derived escalation over the M2/M3 analytical
minimum, driven entirely by the deterministic robust-corner failure
(§11), not by arbitrary conservatism. The escalation is the *minimum*
increment (rounded to each milestone's own stated granularity) shown
to close both the array-power and battery-DoD failure modes
independently.

## 17. Validation strategy

- **Unit tests** (`tests/test_integrated.py`, 29 tests;
  `tests/test_robustness.py`, 36 tests): design/margin validation,
  requirement extraction, margin formulas and double-counting
  avoidance, Monte Carlo determinism and non-mutation of the fixed
  design, Wilson-interval correctness at boundary cases, convergence
  monotonicity, sensitivity-ranking sign checks, robust-corner
  reproducibility and bound compliance, failure-mode classification,
  and hardware-trade-map monotonicity.
- **Script regression tests** (`tests/test_m4_script.py`, 11 tests):
  M1-M3 numbers unchanged, deterministic escalation values, the
  minimum design failing and the final design passing the robust
  corner, deterministic nominal margins and Monte Carlo outcome, and
  the array-only/battery-only insufficiency tests confirming both
  escalations were genuinely necessary.
- 246/246 tests passing as of this milestone.

## 18. Limitations

- No detailed circuit topology, DC/DC converter transients, or MPPT
  control dynamics.
- No cell-temperature model or seasonal beta-angle geometry (eclipse
  fraction remains a direct, sampled input, as in M1-M3).
- No battery electrochemistry, thermal model, C-rate degradation
  model, or cycle-life prediction.
- No vendor hardware selection or detailed mass model.
- Uncertainty parameters are sampled **independently**; no correlation
  structure is modeled (§6) — a stated simplification.
- The one-at-a-time sensitivity method (§12) does not capture
  parameter interaction effects; a variance-based (Sobol) method would
  but is out of scope.
- The deterministic robust corner (§11) is one stated, defensible
  scenario, not an exhaustive worst-case search over all parameter
  combinations.
