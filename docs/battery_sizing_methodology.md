# Methodology — Milestone 3: Battery Sizing, Depth of Discharge & Eclipse Energy Storage

This document defines the battery-sizing and eclipse-storage model
implemented in `src/power_budget/battery.py` and used by
`scripts/size_battery.py`. It builds on Milestone 1
(`docs/methodology.md`) and Milestone 2
(`docs/solar_array_methodology.md`) without modifying either.

## 1. Scope

Milestone 3 answers:

> Given the spacecraft's eclipse energy demand, discharge-path losses,
> allowable depth of discharge, design margin, and representative
> battery aging assumptions, what battery capacity is required and how
> much state-of-charge margin remains through the orbit?

It stops short of electrochemical/equivalent-circuit modeling,
voltage/current transients, cell-temperature effects, detailed
cycle-life prediction, cell balancing, BMS design, or vendor hardware
selection (§29 of the milestone brief; see also §14 below).

## 2. Inputs reused from Milestones 1 and 2 (not recomputed)

`scripts/size_battery.py` calls `build_power_budget()` (M1) and
`size_solar_array()` (M2) exactly as those milestones do, then reads:

- `power_budget.phase_energy["eclipse"].energy_j` → `E_e` (load-side
  eclipse energy)
- `solar_result.t_sun_s`, `solar_result.e_sun_j`,
  `solar_result.p_sa_design_w`, `solar_result.config` (M2's
  `SolarArrayConfig`, in particular `eta_sun_path` and
  `eta_recharge_path`) → used for the recharge-closure check and the
  SOC simulation

The M1/M2 load and array models are never redefined or duplicated in
Milestone 3 code. Accepted M1 numbers (orbit-avg 8.79 W, peak 14.50 W,
sunlight 9.47 Wh, eclipse 4.38 Wh) and M2 numbers (raw array power
15.44 W, design 19.30 W, area 0.065 m²) are regression-tested in
`tests/test_m3_script.py`.

## 3. Battery energy-flow convention

Let `E_e` be load-side eclipse energy [J] and `eta_d` the
battery-to-bus discharge-path efficiency. The energy actually
withdrawn from stored battery energy is:

```
E_batt,out = E_e / eta_d                                [J]
```

implemented in `battery.battery_withdrawal_j()`. This is strictly
larger than `E_e` (baseline: 4.61 Wh withdrawn vs. 4.38 Wh delivered
to loads) and is the quantity that must drive every downstream
capacity/DoD calculation -- never `E_e` directly.

**Note on M2/M3 consistency.** Milestone 2's `eta_recharge_path`
(`eta_c`) is explicitly documented (in `solar.py`) as a *charge-side
only* efficiency: it sizes the array to deposit `E_e` worth of usable
energy into storage, deliberately excluding the discharge loss this
module introduces. Milestone 3's recharge-closure check (§8) therefore
verifies the array's sunlight surplus against the *stricter*,
discharge-inclusive quantity `E_batt,out`, not against `E_e` — see §8.

## 4. Depth of discharge and capacity chain

```
DoD          = E_withdrawn / C_reference                 [-]
C_raw        = E_batt,out / DoD_max                       [J]
C_design,EOL = SF_C * C_raw                                [J]
C_BOL        = C_design,EOL / f_cap,EOL                    [J]
```

implemented in `battery.raw_capacity_j()`,
`battery.design_capacity_eol_j()`, `battery.bol_nameplate_capacity_j()`
respectively. `C_raw` is sized directly against `DoD_max` from the
withdrawal, so it is already an EOL-usable-capacity basis (the battery
must not exceed `DoD_max` even after fade). `SF_C` (capacity design
margin) and `f_cap,EOL` (EOL capacity retention) are two separate,
explicitly labeled multipliers, never folded into `DoD_max` or into
each other (`tests/test_battery.py::test_dod_and_margin_are_kept_separate`).

## 5. Representative battery/EPS assumptions (`BatteryConfig`)

All values are stated, representative systems-level engineering
assumptions — no commercial battery cell or pack is selected or
implied. Every efficiency/retention factor lies in `(0, 1]`;
`capacity_margin >= 1`.

| Symbol | Name | Default | Meaning |
|---|---|---:|---|
| `eta_d` | discharge-path efficiency | 0.95 | battery-to-bus discharge-converter + harness loss |
| `DoD_max` | max allowable depth of discharge | 0.25 | conservative, frequently-cycled LEO Li-ion design point (a stated design choice, not a fitted cycle-life model) |
| `SF_C` | capacity design margin | 1.25 | 25% design/uncertainty margin, kept separate from `DoD_max` |
| `f_cap,EOL` | EOL capacity retention | 0.80 | stated assumption for end-of-life fade; distinct from Milestone 2's photovoltaic `f_eol` |
| capacity step | selected-capacity rounding granularity | 5 Wh | representative pack-assembly granularity (§6) |

## 6. Selecting a practical design capacity

`battery.select_design_capacity_wh()` rounds the analytical minimum
BOL nameplate requirement **up** to the nearest multiple of 5 Wh — a
stated rounding philosophy representative of the capacity granularity
available when a pack is assembled from a discrete number of
series/parallel cells. It never rounds down, and the assumptions
upstream are never adjusted to land on a convenient number. Baseline:
analytical minimum 28.84 Wh → **selected 30.0 Wh**.

## 7. State of charge and the one-orbit SOC profile

```
SOC = E_stored / C_available,   0 <= SOC <= 1
DoD = 1 - SOC                    (measured from a full charge)
```

`battery.simulate_orbit_soc()` integrates SOC over one orbit using the
same piecewise-constant-schedule / phase-boundary sweep technique as
`energy.energy_by_phase()`:

- **Sunlight**: the array (at its M2 design power) covers the raw
  sunlight-load draw (`P_load / eta_sun_path`); any surplus charges
  the battery at rate `surplus * eta_recharge_path`, **clipped** so
  stored energy never exceeds the selected capacity (excess is
  dumped/regulated away — a shunt-regulator-level detail, not modeled,
  per the scope boundary in §14).
- **Eclipse**: the battery discharges to the bus at rate
  `P_load / eta_discharge`.

**Initial condition.** `t = 0` is, by this package's orbit convention,
the instant eclipse ends — i.e. the battery's cycle minimum. When no
explicit `initial_soc` is given, the simulation sets
`SOC(0) = 1 - DoD_actual`, where `DoD_actual = E_batt,out /
C_selected`. This makes the returned profile close periodically by
construction whenever the array fully recharges before the next
eclipse begins (verified in
`tests/test_battery.py::test_baseline_soc_profile_bounds`, which
checks `final_soc == initial_soc`).

**Baseline result:** SOC starts the orbit at 84.6%, rises to 100%
(reaching full ~42.3 min into the 60.9-minute sunlight arc — see §9),
holds at 100% (excess sunlight energy clipped/dumped) until eclipse
entry, then discharges linearly back down to 84.6% by orbit close.
Minimum SOC over the orbit is **84.6%**, well above the
`1 - DoD_max = 75%` limit line shown in Figure 1 — confirming the
selected, margined capacity operates comfortably inside its allowable
cycling depth.

## 8. Recharge closure (M2 ↔ M3 consistency)

`battery.verify_recharge_closure()` independently recomputes the
sunlight recharge surplus available to the battery, using the *same*
`eta_sun_path`/`eta_recharge_path` from the M2 `SolarArrayConfig` (no
new efficiency is introduced):

```
available_j = eta_c * max(P_SA,design * t_sun - E_s / eta_s, 0)
required_j  = E_batt,out            (the stricter, discharge-inclusive quantity)
closes      ⇔ available_j >= required_j
```

Baseline: available **7.72 Wh** vs. required **4.61 Wh** — closes with
**+67.2%** margin. This is larger than Milestone 2's own +25.0% array
design margin because it compounds M2's array margin with the extra
headroom built into the M3 battery's selected (rounded, margined,
EOL-derated) capacity, which recharges to full well before eclipse
begins.

## 9. Recharge time

The SOC simulation locates the exact instant SOC first reaches 100%
(linear interpolation within the constant-power segment where the
crossing occurs — the stored-energy trace is exactly piecewise-linear,
so this is exact, not a numerical approximation). Baseline:
**42.3 min**, i.e. **69.4%** of the 60.9-minute sunlight arc — a
meaningful operational headroom metric: the battery does not need the
full sunlight window to recharge.

## 10. Baseline result (this milestone)

Regenerate with `python scripts/size_battery.py`; canonical output in
`results/m3_battery_sizing.md`.

| Quantity | Value |
|---|---:|
| Eclipse load energy | 4.38 Wh |
| Discharge efficiency | 0.95 |
| Battery withdrawal | 4.61 Wh |
| Max DoD | 0.25 |
| Raw capacity | 18.46 Wh |
| Capacity margin | 1.25 |
| EOL required capacity | 23.07 Wh |
| EOL retention | 0.80 |
| Minimum BOL nameplate | 28.84 Wh |
| Selected design capacity | 30.0 Wh |
| Actual DoD at selected capacity | 15.4% |
| Baseline minimum SOC | 84.6% |
| Recharge time / utilization | 42.3 min (69.4% of sunlight) |
| Recharge closure margin | +67.2% (closes) |

## 11. Sensitivity findings

- **Eclipse fraction** `f_e` ∈ {0.20 … 0.45}: raw capacity rises
  monotonically and nearly linearly, 9.0 Wh → 20.3 Wh.
- **Max DoD** `DoD_max` ∈ {0.15, 0.20, 0.25, 0.30, 0.40}: raw capacity
  scales as `1/DoD_max` exactly (30.76 Wh at 0.15 → 11.54 Wh at 0.40,
  verified to `1e-9` relative tolerance) — the single strongest
  first-order sizing driver in this model.
- **Discharge efficiency** `eta_d` ∈ {0.80 … 1.00}: raw capacity scales
  as `1/eta_d` exactly, 21.9 Wh → 17.5 Wh — a real but comparatively
  secondary driver next to `DoD_max` (a 20-point swing in `eta_d`
  moves capacity ~25%, vs. a 0.15-point swing in `DoD_max` more than
  doubling it).
- **EOL capacity retention** `f_cap,EOL` ∈ {1.0, 0.9, 0.8, 0.7}: BOL
  nameplate scales as `1/f_cap,EOL` exactly, 23.07 Wh → 32.96 Wh.
- **Capacity margin** `SF_C` ∈ {1.0, 1.1, 1.2, 1.3}: design-EOL
  capacity scales exactly linearly with `SF_C`.
- **Communications (downlink) duty** — occurs entirely in eclipse in
  the baseline schedule: sweeping downlink duration 0 → 25 min raises
  raw capacity monotonically, 16.07 Wh → 22.04 Wh.
- **Payload (imaging) duty** — occurs entirely in sunlight in the
  baseline schedule: sweeping payload duration 0 → 40 min leaves raw
  capacity **completely unchanged** (18.457 Wh at every duration,
  identical to better than 1e-6 Wh) even though the same sweep moved
  Milestone 2's required array area substantially (§19 of the M2
  docs). This is reported honestly as observed, not smoothed over —
  it directly demonstrates that **battery sizing depends on *when*
  energy is consumed, not merely on total orbit-average duty cycle.**

## 12. Activity-timing experiment

A controlled experiment (`scripts/size_battery.py::run_timing_experiment`):
hold a fixed 600 s / 10.2 W downlink activity's duration and power
constant, but place it either (a) fully inside the sunlight arc or (b)
fully inside the eclipse arc, on an otherwise NOMINAL-only orbit.

| Placement | Orbit-avg power | Total energy/orbit | Eclipse energy | Array design power | Battery raw capacity |
|---|---:|---:|---:|---:|---:|
| Sunlight | 7.159 W | 11.29 Wh | 3.82 Wh | 15.75 W | 16.07 Wh |
| Eclipse | 7.159 W | 11.29 Wh | 4.38 Wh | 15.79 W | 18.46 Wh |

Orbit-average power and total energy per orbit are **identical to 9
significant figures** between the two placements (they depend only on
mode durations and powers, not timing) — regression-tested in
`test_timing_experiment_orbit_energy_invariant`. Array design power
shifts only slightly (15.75 W → 15.79 W), because Milestone 2's
sizing equation divides sunlight energy by `eta_sun_path` (0.90) and
eclipse energy by `eta_recharge_path` (0.85) — moving energy into the
less-efficient eclipse path costs slightly more raw array output.
**Battery raw capacity, in contrast, rises by 15%** (16.07 → 18.46 Wh)
— a first-order effect, because it depends only on how much energy is
consumed *specifically during eclipse*, not on total orbit energy.
This is the central Milestone-3 systems-engineering result: **activity
timing, not just orbit-average duty cycle, drives battery sizing.**

## 13. Validation strategy

- **Unit tests** (`tests/test_battery.py`, 48 tests): config
  validation, sizing-chain formulas, DoD/margin/EOL separation,
  rounding behavior, recharge-closure exactness and failure case,
  end-to-end sizing against the M1 fixture schedule, SOC/DoD bounds
  and relationship, eclipse-only-discharges / sunlight-only-charges
  sanity checks, an explicit undersized-battery rejection test, an
  explicit sunlight-deficit rejection test, and inverse/linear scaling
  checks for every sensitivity axis.
- **Script regression tests** (`tests/test_m3_script.py`, 15 tests):
  M1/M2 numbers unchanged, deterministic M3 headline numbers, sweep
  monotonicity/scaling exactness, the payload-insensitivity finding,
  and the full activity-timing experiment (including a from-first-
  principles sanity check of the experiment's own construction).
- A real defect was found and fixed during this milestone's
  development: the recharge-time interpolation initially computed its
  fractional crossing point using the *post-clip* stored energy,
  which made it always evaluate to the segment's end time whenever
  clipping occurred (silently reporting recharge time = 100% of
  sunlight duration regardless of the true crossing instant). Fixed by
  interpolating against the pre-clip projected energy; the corrected
  value (42.3 min, 69.4% of sunlight) was verified by an independent
  hand calculation before being locked into the regression suite
  (`test_m3_headline_numbers_deterministic`).
- 170/170 tests passing as of this milestone.

## 14. Limitations (explicitly out of scope, deferred to later milestones)

- No electrochemical equivalent-circuit model, no voltage/current
  transient behavior.
- No C-rate constraint beyond the implicit sanity check that discharge
  power stays within the modeled schedule (no explicit max-C-rate
  limit is enforced).
- No cell-temperature dependence of capacity or efficiency.
- No battery thermal model.
- No detailed cycle-life / calendar-aging prediction — `f_cap,EOL` and
  `DoD_max` are stated design assumptions, not fitted degradation
  curves.
- No cell balancing or battery-management-electronics model.
- No vendor hardware selection.
- No detailed MPPT/charge-controller electronics — the charge/discharge
  paths remain the same lumped, representative efficiencies introduced
  in Milestones 2 and 3.
- No fault-tolerant/redundant battery architecture.
- The SOC simulation does not model battery assist during a sunlight
  power deficit (array output momentarily below raw sunlight-load
  draw); it raises an explicit error if this occurs rather than
  silently mis-modeling it. It does not occur for the baseline mission
  or any sweep in this milestone (verified by the sweeps completing
  without error), since peak raw sunlight-phase load draw
  (16.11 W) stays below the design array output (19.30 W) throughout.
