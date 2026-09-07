# Methodology — Milestone 2: Solar Array Sizing & Sunlight Energy Closure

This document defines the solar-array sizing model implemented in
`src/power_budget/solar.py` and used by
`scripts/size_solar_array.py`. It builds directly on top of Milestone
1 (`docs/methodology.md`) without modifying it.

## 1. Scope

Milestone 2 answers:

> How much solar-array power and area are required during sunlight to
> operate the spacecraft and replace the energy consumed during
> eclipse before the next eclipse begins?

It explicitly does **not** size the battery (capacity, depth of
discharge, cycle life, chemistry) -- that is Milestone 3. This
milestone stops at: how much electrical energy must the array put
*into* the bus/storage during sunlight, and how much collecting area
does that require.

## 2. Inputs reused from Milestone 1 (not recomputed)

`scripts/size_solar_array.py` calls
`power_budget.budget.build_power_budget()` exactly as Milestone 1
does, then reads:

- `power_budget.phase_energy["sunlight"].duration_s` → `t_sun_s`
- `power_budget.phase_energy["sunlight"].energy_j` → `E_s`
- `power_budget.phase_energy["eclipse"].energy_j` → `E_e`
- `power_budget.orbit_average_power_w` → `P_avg` (for the naive-sizing
  comparison, §5)

The Milestone-1 load model (modes, schedule, orbit geometry) is never
redefined or duplicated in Milestone 2 code. The accepted M1 baseline
numbers (orbit-average power 8.79 W, peak 14.50 W, sunlight energy
9.47 Wh, eclipse energy 4.38 Wh) are regression-tested in
`tests/test_m2_script.py::test_m1_baseline_numbers_unchanged`.

## 3. Why orbit-average power is not the array requirement

The array is only physically able to generate power while the
spacecraft is in sunlight, for a duration `t_sun < T_orbit`. During
that shorter window it must supply:

1. the electrical loads that are active *during* sunlight, and
2. enough surplus energy to fully replace whatever the spacecraft
   drew from storage during the eclipse arc,

both transmitted through lossy conversion paths. A naive sizing to
`P_avg = (E_s + E_e) / T_orbit` implicitly assumes the array could
generate for the *entire* orbit including eclipse (physically
impossible) and ignores conversion losses -- it therefore
systematically undersizes the array. Section 8 quantifies this gap for
the baseline mission: the raw sunlight-only requirement is **1.76x**
naive average-power sizing.

## 4. Sizing equation

Let `E_s`, `E_e` be sunlight/eclipse load energy [J], `t_s` sunlight
duration [s], `eta_s` the array-to-sunlight-load path efficiency, and
`eta_c` the effective eclipse-energy recharge-path efficiency. The raw
required array electrical output is:

```
P_SA,raw = (E_s / eta_s + E_e / eta_c) / t_s          [W]
```

Implemented in `solar.required_array_power_raw_w()`. `E_s / eta_s` is
the raw array output needed to deliver `E_s` to sunlight loads after
path losses; `E_e / eta_c` is the raw array output needed to deposit
enough energy into the recharge path that `E_e` worth of usable energy
is available for eclipse discharge. Both are expressed as array-side
(pre-loss) energy so they can be summed directly and divided by the
sunlight duration over which the array must produce them.

## 5. Design margin (kept separate from everything else)

```
P_SA,design = SF_P * P_SA,raw
```

`SF_P` (`design_margin` in `SolarArrayConfig`) defaults to **1.25**
(25%), a representative baseline design/load-growth margin for
early-phase smallsat EPS sizing. It is applied as a single scalar
*after* the raw requirement (`solar.required_array_power_design_w()`)
and is never folded into a cell, path, or degradation efficiency —
every table and figure in this milestone reports raw and
design/margined values as separate columns/series so the margin's
effect is directly visible (`tests/test_solar.py::test_raw_and_design_are_kept_separate_not_conflated`).

## 6. Representative EPS/array assumptions (`SolarArrayConfig`)

All values below are stated, representative engineering assumptions —
not sourced commercial hardware specifications. Every efficiency
factor is validated to lie in `(0, 1]`
(`solar._check_unit_interval`); `design_margin >= 1`.

| Symbol | Name | Default | Meaning |
|---|---|---:|---|
| `S0` | solar constant | 1361 W/m² | representative value near 1 AU, treated as fixed (no orbital-distance/seasonal model) |
| `eta_cell` | BOL cell efficiency | 0.30 | representative modern multi-junction smallsat cell (technology class, not a vendor part) |
| `f_array` | array derating factor | 0.85 | single lumped factor for non-normal incidence, packing density, interconnect area, and practical utilization |
| `f_EOL` | end-of-life degradation | 0.85 | radiation + thermal-cycling power loss over mission life, kept separate from `design_margin` |
| `eta_sun_path` | array→sunlight-load efficiency | 0.90 | regulation + harness losses on the direct-support path |
| `eta_recharge_path` | eclipse-recharge-path efficiency | 0.85 | battery charge-conversion losses on the energy-storage path (battery *discharge* efficiency belongs to Milestone 3, since this module only sizes energy going *into* storage) |
| `SF_P` | design margin | 1.25 | 25% design/load-growth margin, applied after the raw requirement |

## 7. Power-density chain (BOL → EOL)

```
p_BOL        = S0 * eta_cell * f_array                 [W/m^2]
p_usable,EOL = p_BOL * f_EOL                            [W/m^2]
```

Implemented in `solar.bol_power_density_w_m2()` and
`solar.eol_power_density_w_m2()`. Degradation (`f_EOL`) derates the
*technology* (how much power a given area produces after mission
life); design margin (`SF_P`, §5) inflates the *requirement*. These
are never combined into one factor.

## 8. Array area

```
A_SA = P_SA,design / p_usable,EOL                       [m^2]
```

`solar.required_array_area_m2()`. Baseline result: **0.065 m²**
(see §11 for the full baseline table). This is a plausible order of
magnitude for a 3U-cubesat-class deployable panel area, consistent
with the assumed technology-class efficiencies — not derived from or
implying any specific commercial product.

## 9. Independent energy-closure verification

For the *selected* design array power, `solar.verify_energy_closure()`
independently recomputes the raw-equivalent requirement directly from
`E_s`/`E_e` (not from a cached intermediate result) and checks:

```
E_generated,sun = P_SA,design * t_s
E_required      = E_s / eta_s + E_e / eta_c
closes          ⇔ E_generated,sun >= E_required
margin_fraction = E_generated,sun / E_required - 1
```

By construction, `margin_fraction == SF_P - 1` exactly (up to floating
point) whenever the design power came from
`required_array_power_design_w()` — this is asserted directly in
`tests/test_solar.py::test_energy_closure_margin_fraction_matches_design_margin`
and exercised end-to-end for the baseline mission in
`test_size_solar_array_end_to_end`.

## 10. Naive-vs-correct sizing comparison

`SolarArraySizingResult.raw_to_avg_ratio = P_SA,raw / P_avg`. For the
baseline mission this is **1.76**: the physically correct sunlight-only
recharge requirement is 76% larger than naive average-power sizing.
The gap is driven by two effects compounding: (a) the array only has
60.9 of the 94.6-minute orbit (64%) to do all its work, and (b)
conversion losses on both the sunlight-support and recharge paths
inflate the raw electrical output needed above the electrical energy
actually delivered to the loads/battery.

## 11. Baseline result (this milestone)

Regenerate with `python scripts/size_solar_array.py`; canonical output
in `results/m2_solar_array_sizing.md`.

| Quantity | Value |
|---|---:|
| Sunlight duration | 60.9 min |
| Naive avg-power estimate (`P_avg`) | 8.79 W |
| Raw required array power | 15.44 W (1.76x `P_avg`) |
| Design array power (`SF_P` = 1.25) | 19.30 W |
| BOL usable power density | 347.1 W/m² |
| EOL usable power density | 295.0 W/m² |
| Required array area | 0.065 m² |
| Energy closure margin | +25.0% (closes) |

## 12. Sensitivity results

All sweeps in `scripts/size_solar_array.py`, cross-checked analytically
in `tests/test_solar.py` and `tests/test_m2_script.py`.

- **Eclipse fraction** `f_e` ∈ {0.20, 0.30, 0.356, 0.40, 0.45}: design
  array power rises 11.9 W → 17.6 W and area 0.040 m² → 0.060 m²,
  monotonically. Less sunlight time means both less time to recharge
  and more energy to recharge (longer eclipse), a compounding penalty.
- **Recharge-path efficiency** `eta_c` ∈ {0.60 … 0.95}: area falls
  monotonically from 0.074 m² to 0.063 m² as charge-path efficiency
  improves — poorer charge efficiency directly inflates the raw
  requirement (`E_e / eta_c` grows as `eta_c` shrinks).
- **EOL degradation** `f_EOL` ∈ {1.0, 0.9, 0.8, 0.7}: area scales as
  `1 / f_EOL` exactly (verified to `1e-9` relative tolerance in
  `test_sweep_eol_degradation_inverse_scaling`) — 0.056 m² → 0.079 m².
- **Cell efficiency** `eta_cell` ∈ {0.15 … 0.35}: area scales as
  `1 / eta_cell` exactly — 0.131 m² at 15% cell efficiency down to
  0.056 m² at 35%, distinguishing the *mission energy requirement*
  (fixed) from the *technology-dependent area* (inversely
  proportional to cell efficiency).
- **Design margin** `SF_P` ∈ {1.0, 1.1, 1.2, 1.3}: both design power
  and area scale exactly linearly with `SF_P` (verified to `1e-9`
  relative tolerance).
- **Communications (downlink) duty**: sweeping downlink duration
  0 → 25 min raises required area 0.063 m² → 0.070 m².
- **Payload (imaging) duty**: sweeping payload duration 0 → 40 min
  raises required area 0.054 m² → 0.077 m² — a *steeper* slope than
  the communications sweep, because the payload mode's bus power
  (14.5 W) exceeds the downlink mode's (10.2 W); confirmed directly in
  `test_payload_duty_is_stronger_area_driver_than_comms_duty`.

## 13. Validation strategy

- **Unit tests** (`tests/test_solar.py`, 50 tests): config validation
  (efficiency/margin bounds), BOL/EOL density formula and ordering,
  raw/design separation, area formula, energy-closure exactness at
  unity margin and at the baseline margin, monotonicity/inverse-scaling
  direction checks for every sensitivity axis, and an end-to-end check
  against the Milestone-1 fixture schedule.
- **Script regression tests** (`tests/test_m2_script.py`, 16 tests):
  M1 numbers unchanged, `build_schedule()` defaults reproduce the
  frozen `BASELINE_SCHEDULE` exactly, zero-duration edge cases collapse
  cleanly, deterministic headline M2 numbers, and monotonicity across
  every sweep the script generates.
- 107/107 tests passing as of this milestone.

## 14. Limitations (explicitly out of scope, deferred to later milestones)

- No battery capacity, depth-of-discharge, cycle-life, or chemistry
  model (Milestone 3).
- No MPPT tracking-efficiency model — `eta_sun_path` /
  `eta_recharge_path` are lumped, representative path efficiencies.
- No cell-temperature model (power density does not vary with
  operating temperature).
- No seasonal beta-angle / eclipse-fraction-vs-time-of-year geometry —
  `eclipse_fraction` remains a direct Milestone-1 input.
- No articulated array pointing or off-normal-incidence time history —
  `f_array` is a single time-averaged derating factor, not a pointing
  simulation.
- No shadow/penumbra transition modeling — eclipse entry/exit is
  treated as instantaneous (inherited from Milestone 1's orbit model).
- No harness-level circuit design or vendor hardware selection.
