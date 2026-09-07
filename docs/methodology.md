# Methodology — Milestone 1: EPS Foundations, Operating Modes & Energy Balance

This document defines the deterministic power/energy accounting model
implemented in `src/power_budget/` and used by
`scripts/run_power_budget.py`.

## 1. Scope

Milestone 1 answers exactly one question:

> Given a spacecraft operating-mode schedule over one orbit, what are
> the instantaneous power profile, orbit-average power, sunlight
> energy use, eclipse energy use, and peak bus-power demand?

It intentionally stops short of solar-array and battery sizing
(Milestones 2–3): those require additional models (solar-cell
degradation, panel area/pointing losses, DoD/temperature-derated
battery capacity) layered on top of this energy-balance core.

## 2. Time and geometry convention

- `t = 0` is defined as the instant the spacecraft exits eclipse and
  enters sunlight (see `OrbitGeometry` in
  [`orbit.py`](../src/power_budget/orbit.py)).
- The orbit is split into two contiguous arcs:
  - **Sunlight**: `[0, T_sun)` where `T_sun = T_orbit * (1 - f_eclipse)`
  - **Eclipse**: `[T_sun, T_orbit)`
- This avoids any wraparound arithmetic in the schedule/energy code.
  Operating-mode boundaries need not align with the sunlight/eclipse
  boundary — a mode span may straddle the terminator, and the energy
  integrator (§4) handles that correctly by sub-dividing at every
  boundary crossing.
- Eclipse fraction `f_eclipse` is treated as a direct input in this
  milestone. Deriving it from orbit altitude, inclination and beta
  angle is deferred to a later milestone; until then it is a
  representative engineering assumption, stated explicitly wherever
  used (see [`scripts/mission_baseline.py`](../scripts/mission_baseline.py)).

## 3. Operating modes and schedule

- A `Mode` (see [`modes.py`](../src/power_budget/modes.py)) is a named
  electrical load state with a single representative **average** bus
  power draw in watts. Transient/inrush behavior is out of scope for
  Milestone 1.
- An `OrbitSchedule` (see [`schedule.py`](../src/power_budget/schedule.py))
  is an ordered list of `ScheduleEntry(mode, start_s, end_s)` spans
  that must **exactly tile** `[0, T_orbit)` — no gaps, no overlaps,
  starting at `t = 0` and ending at `t = T_orbit`. This is a
  deliberate correctness constraint: every second of the orbit is
  attributed to exactly one named mode, so total accounted energy is
  unambiguous by construction (validated in
  `OrbitSchedule.__post_init__` and exercised in
  `tests/test_schedule.py`).

## 4. Power and energy calculations

Let a schedule consist of spans `i = 1..N`, each with power `P_i` [W]
and duration `Δt_i` [s].

**Total energy per orbit** (exact analytic sum, not numerical
quadrature):

```
E_total = Σ_i  P_i · Δt_i           [J]
```

**Orbit-average power**:

```
P_avg = E_total / T_orbit           [W]
```

**Peak bus power**:

```
P_peak = max_i ( P_i )              [W]
```

**Sunlight/eclipse energy split.** A schedule span may straddle the
sunlight/eclipse terminator (e.g. a housekeeping block that starts
before and ends after eclipse entry). `energy.energy_by_phase()`
handles this by taking the union of all schedule-entry boundaries and
the single eclipse boundary, sweeping the resulting sorted breakpoints,
and attributing each resulting sub-interval's `P · Δt` to whichever
phase (`sunlight` / `eclipse`) is active at its midpoint. This
guarantees, for any schedule:

```
E_sunlight + E_eclipse == E_total
T_sunlight + T_eclipse == T_orbit
```

Both invariants are asserted directly in
`tests/test_energy.py::test_energy_by_phase_straddling_mode`.

All of the above are computed **analytically** from the piecewise-
constant schedule — never by trapezoidal integration of a sampled
trace. `energy.power_profile()` produces a *sampled* trace purely for
plotting; `tests/test_energy.py::test_power_profile_integral_matches_analytic_energy`
cross-checks that a fine-resolution trapezoidal integral of that trace
agrees with the analytic energy to within 0.1%, as a consistency check
on the sampler (not as the source of truth).

## 5. Per-mode power-budget table

`budget.build_power_budget()` aggregates all schedule spans by mode
name into one row per unique mode (a mode may recur, e.g. multiple
downlink passes), reporting:

| column | meaning | unit |
|---|---|---|
| `power_w` | mode's representative bus power | W |
| `duty_cycle` | mode's total duration ÷ orbit period | – |
| `duration_s` | total time in this mode over one orbit | s |
| `energy_j` | total energy consumed by this mode | J |
| `energy_wh` | same, in watt-hours | Wh |
| `n_spans` | number of separate schedule spans for this mode | – |

Row-sum invariants (`Σ duty_cycle == 1`, `Σ energy_j == E_total`) are
checked in `tests/test_budget.py`.

## 6. Baseline mission assumptions (Milestone 1 example)

Defined once in
[`scripts/mission_baseline.py`](../scripts/mission_baseline.py) and
reused by every script/figure so the mission definition lives in a
single place. Representative 3U-cubesat-class LEO Earth-observation
mission — **illustrative assumptions, not sourced hardware specs**:

| parameter | value | note |
|---|---|---|
| orbit period | 5676 s (94.6 min) | ~500 km circular LEO |
| eclipse fraction | 0.356 | representative for ~500 km, non-terminator orbit |
| `safe` | 3.2 W | beacon RX + minimal ADCS |
| `nominal` | 6.8 W | OBC + ADCS + RX + thermal housekeeping |
| `payload_imaging` | 14.5 W | camera + onboard processing + ADCS pointing |
| `downlink` | 10.2 W | S-band TX + OBC + ADCS pointing |
| `detumble` | 4.5 W | B-dot contingency mode (defined, not scheduled in baseline) |

Baseline schedule: one 20-minute imaging pass mid-sunlight, one
10-minute downlink pass that occurs in eclipse near the terminator,
remainder in nominal housekeeping (one housekeeping span straddles the
eclipse entry, exercising the phase-split logic in a realistic case).

## 7. Results (baseline mission, this milestone)

Regenerate with `python scripts/run_power_budget.py`; canonical output
lives in `results/power_budget_table.csv`,
`results/power_budget_summary.txt`, and `results/figures/`.

- Orbit-average power: **8.79 W**
- Peak bus power: **14.50 W** (payload imaging)
- Total energy/orbit: **13.85 Wh**
- Sunlight energy: **9.47 Wh** (avg 9.33 W over the 60.9 min sunlit arc)
- Eclipse energy: **4.38 Wh** (avg 7.81 W over the 33.7 min eclipse arc)

These sunlight/eclipse energies are the direct inputs to solar-array
sizing (must generate ≥ sunlight-arc demand *and* replace eclipse-arc
depletion) and battery sizing (must supply the full 4.38 Wh eclipse
draw at the required depth-of-discharge margin) in Milestones 2–3.

## 8. Validation strategy

- **Unit tests** (`tests/`) cover: input validation (negative power,
  NaN, zero/negative durations, non-monotonic or non-covering
  schedules), geometry edge cases (zero eclipse fraction, phase
  wraparound across multiple orbits), the terminator-straddling energy
  split, and the aggregate power-budget table's row-sum invariants.
- **Cross-check**: analytic energy vs. trapezoidal integral of a
  finely sampled power profile (§4).
- 41/41 tests passing as of this milestone; see `pytest -q` output in
  the milestone report.
