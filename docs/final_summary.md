# Final Summary — Smallsat EPS Sizing (GNC-05)

A concise, standalone engineering handoff for this project's final
state. Detailed derivations live in the per-milestone documents under
`docs/`; this document stands on its own.

## Mission baseline

Representative 3U-cubesat-class LEO Earth-observation mission — every
number below is a stated engineering assumption, not a sourced
commercial hardware spec.

| Parameter | Value |
|---|---:|
| Orbit period | 94.6 min |
| Eclipse fraction | 0.356 |
| Orbit-average load | 8.79 W |
| Peak bus load | 14.50 W |
| Total energy/orbit | 13.85 Wh |
| Sunlight energy/orbit | 9.47 Wh |
| Eclipse energy/orbit | 4.38 Wh |

## Final hardware recommendation

| | M2 analytical / M3 selected (pre-robustness) | **Final selected** |
|---|---:|---:|
| Solar-array area | 0.0654 m² (M2 analytical minimum) | **0.085 m²** |
| Array EOL electrical output | 19.30 W | **25.07 W** |
| Battery BOL nameplate capacity | 30.0 Wh (M3 selected, rounded from 28.84 Wh) | **35.0 Wh** |
| Battery EOL capacity | 24.0 Wh | **28.0 Wh** |
| Deterministic robust-corner check | FAILS (solar deficit + DoD exceeded) | **PASSES** |
| Monte Carlo closure (N=10,000, seed=42) | not applicable | **99.99%** (95% CI 99.94–100.00%) |

The final design escalates the M2-analytical array and the M3-selected
battery by the smallest practical increment (array +30%, battery +17%
relative to the M3 selection) that closes a single, documented,
deterministic robust-design corner — not arbitrary conservatism.
Neither escalation is larger than the robust corner demonstrably
requires.

## Key equations

**Load/energy accounting** (Milestone 1): orbit-average power, peak
power, and sunlight/eclipse energy from an analytically-integrated
piecewise-constant operating-mode schedule.

**Solar-array sizing** (Milestone 2):

```
P_SA,raw    = (E_sunlight/eta_sun_path + E_eclipse/eta_recharge_path) / t_sunlight
P_SA,design = SF_P * P_SA,raw
p_usable,EOL = S0 * eta_cell * f_array * f_EOL
A_SA        = P_SA,design / p_usable,EOL
```

**Battery sizing** (Milestone 3):

```
E_batt,out   = E_eclipse / eta_discharge
C_raw        = E_batt,out / DoD_max
C_design,EOL = SF_C * C_raw
C_BOL        = C_design,EOL / f_cap,EOL
```

**Integrated margins** (Milestone 4), evaluated at EOL for the final
design against the nominal baseline mission — kept as four separate,
non-collapsed ratios, never one ambiguous "EPS margin":

```
M_E = E_available,sun,EOL / E_required,sun+recharge      (solar energy margin)
M_P = P_array,EOL / P_array,required,raw                  (array power margin)
M_B = DoD_max * C_available,EOL / E_batt,withdrawal        (battery energy margin)
M_R = t_sunlight / t_recharge                               (recharge-time margin)
```

## Key margins (final design, nominal baseline mission)

| Margin | Value |
|---|---:|
| Solar energy margin | 1.624× |
| Array power margin | 1.624× |
| Battery energy margin | 1.517× |
| Recharge-time margin | 3.277× |
| Battery-side recharge closure (available vs. withdrawal) | +67.2% |

## Deterministic robust corner

One defensible scenario: every one of eleven uncertain parameters
shifted roughly 1–2σ toward its unfavorable direction (load +2σ,
communications/payload duty +1.5σ/+1σ, eclipse fraction +2.2σ ≈ 0.40;
cell efficiency, array factor, PV EOL degradation, both path
efficiencies, discharge efficiency, and battery EOL retention each
−1σ) — not every variable stacked at its absolute physical extreme.

- The M2-analytical/M3-selected pre-robustness design (0.0654 m² /
  30 Wh) **fails** this corner via **two independent failure modes**:
  array output cannot cover instantaneous sunlight-phase load
  (`solar_deficit`), and — even after fixing the array alone — actual
  depth of discharge exceeds the 25% limit (`dod_exceeded`).
- The final design (0.085 m² / 35 Wh) **passes** with margin (solar
  recharge margin 1.29×, actual DoD 22.2% < 25% limit).

## Monte Carlo result

N = 10,000 independent realizations, deterministic seed = 42, fixed
final hardware (never resized per realization).

| Result | Value |
|---|---:|
| Closure probability | 99.99% |
| 95% Wilson confidence interval | [99.94%, 100.00%] |
| Observed failure mode | `solar_energy_deficit` (1 of 1 failures) |
| Median solar recharge margin | ≈2.7× |
| Median minimum SOC | ≈84% |
| Median recharge utilization | ≈30% of sunlight |

This closure probability is **conditional on the stated uncertainty
model** (representative, independent, bounded-normal distributions
around each Milestone 1–3 nominal value) — it is not a calibrated
on-orbit reliability figure. With only one failed realization in
10,000, the observed failure mode should be read as *the one instance
observed*, not as a statistically established dominant mode. The
deterministic robust corner above complements this campaign rather
than duplicating it: it checks one specific, reasoned combination of
unfavorable conditions exactly, rather than relying on that
combination arising by chance in a random draw.

## Operating-envelope result

For the fixed final design, sweeping eclipse fraction (0.20–0.50)
against communications duty (0.5×–4.5× baseline): every combination is
feasible for eclipse fraction up to 0.425, at any communications duty
tested. Infeasibility appears only where eclipse fraction reaches
~0.46–0.50 combined with communications duty at or above ~2.5–3.0×
baseline — far beyond the baseline mission's own operating point
(eclipse fraction 0.356, communications duty 1.0×).

## Top sensitivities (one-at-a-time, ±1σ, final design)

1. Spacecraft load level and eclipse fraction (~8.5–8.6% swing in
   solar recharge margin per 1σ) — the two mission-side drivers
   dominate.
2. PV cell efficiency (~8.5%) — the strongest single array-technology
   driver.
3. Array EOL degradation and array packing/incidence factor (~6.0%
   each).
4. Battery EOL capacity retention (~5.0% swing in actual DoD) — the
   dominant battery-specific driver.

Method: finite-difference perturbation of each parameter by ±1
standard deviation, holding all others at nominal, normalized to
fractional change in the output metric. This does not capture
parameter interaction effects (a variance-based/Sobol method would).

## Verification status

- **246/246 tests passing** across all four milestones; nothing
  weakened as later milestones were added.
- Every sizing equation has a corresponding scaling-law regression test
  (inverse, linear, or exact-ratio, to 1e-9 where applicable).
- Monte Carlo determinism, non-mutation of fixed hardware during
  robustness evaluation, Wilson-interval correctness, and convergence
  monotonicity are all regression-tested.
- Clean-environment installation (fresh venv, `pip install -e ".[dev]"`
  per the README) reproduces the full test suite and both M1 and M4
  scripts byte-identically.
- All four analysis scripts (`run_power_budget.py`, `size_solar_array.py`,
  `size_battery.py`, `final_eps_study.py`) exit 0, produce no warnings,
  and regenerate every tracked table/figure byte-identically.

## Assumptions

- All EPS/mission values are stated representative engineering
  assumptions unless a source is cited — no invented commercial
  hardware specs.
- SI base units throughout the core library; Wh/minutes/percent carry
  an explicit suffix and appear only at the reporting layer.
- Milestone 4's eleven uncertainty parameters are sampled
  **independently** (no correlation structure).
- `DoD_max` (the battery's operational cycling limit) is treated as a
  fixed policy threshold, never sampled as uncertain.

## Limitations

- No electrochemistry, thermal, circuit-topology, MPPT-control,
  seasonal beta-angle geometry, or cycle-life models — this is a
  systems-level sizing study, not a detailed hardware design.
- No correlation structure between uncertainty parameters (§ above).
- The one-at-a-time sensitivity method does not capture parameter
  interaction effects.
- The deterministic robust corner is one defensible scenario, not an
  exhaustive worst-case search over all parameter combinations.
- The Monte Carlo closure probability is model-conditional, not a
  calibrated flight-reliability estimate.

## Where to look next

- [`README.md`](../README.md) — project overview and portfolio narrative.
- [`docs/methodology.md`](methodology.md) — Milestone 1 (loads/energy).
- [`docs/solar_array_methodology.md`](solar_array_methodology.md) — Milestone 2 (array sizing).
- [`docs/battery_sizing_methodology.md`](battery_sizing_methodology.md) — Milestone 3 (battery sizing).
- [`docs/integrated_eps_methodology.md`](integrated_eps_methodology.md) — Milestone 4 (robustness, final sizing).
- `results/` — every generated table (CSV/Markdown) and figure (PNG) referenced above.
