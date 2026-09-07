# GNC-05 — Smallsat Power Budget

A coding-focused spacecraft electrical power system (EPS) sizing
portfolio project. Converts mission operating modes, eclipse fraction,
and duty cycle into a defensible **power budget, solar-array
requirement, and battery requirement**, built as a reusable, tested
Python package rather than a one-off notebook.

## Status

**Milestone 1 — EPS Foundations, Operating Modes & Energy Balance**
(complete) and **Milestone 2 — Solar Array Sizing & Sunlight Energy
Closure** (complete). See [`docs/methodology.md`](docs/methodology.md)
and [`docs/solar_array_methodology.md`](docs/solar_array_methodology.md)
for the full write-ups. Battery sizing is the next milestone and is
not yet implemented.

## What's here

```
src/power_budget/     Core package (deterministic power/energy accounting)
  modes.py              Operating-mode definitions (Mode, ModeSet)
  orbit.py               Orbit period / eclipse-fraction geometry
  schedule.py            Full-coverage mode timeline over one orbit
  energy.py               Power-profile sampling + analytic energy integration
  budget.py                Per-mode power-budget table + orbit summary
  solar.py                  Solar-array sizing: sunlight-only energy closure (M2)
tests/                 pytest suite (unit tests + invariant checks)
scripts/
  mission_baseline.py    Baseline mission definition (orbit, modes, schedule)
  run_power_budget.py    M1: runs the load analysis, writes table + figures
  size_solar_array.py    M2: sizes the solar array, writes tables + figures
docs/
  methodology.md               M1 methodology, equations, and assumptions
  solar_array_methodology.md   M2 methodology, sizing equation, sensitivities
results/               Generated tables (CSV/MD), summaries (txt), figures (PNG)
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                            # run the test suite
python scripts/run_power_budget.py   # M1: regenerate table + figures
python scripts/size_solar_array.py   # M2: regenerate array sizing + figures
```

Outputs land in `results/`:
- `power_budget_table.csv` — per-mode power/duty-cycle/energy table
- `power_budget_summary.txt` — orbit-average power, peak power, sunlight/eclipse energy
- `figures/power_profile.png` — instantaneous bus power over one orbit
- `figures/mode_energy.png` — per-mode energy contribution
- `m2_solar_array_sizing.md` — raw/design array power, BOL/EOL density, area, energy closure
- `m2_eclipse_fraction_sweep.csv` — required array power/area vs. eclipse fraction
- `figures/m2_energy_flow.png` — orbital energy flow (sunlight load / eclipse recharge / margin)
- `figures/m2_eclipse_sensitivity.png` — array power/area vs. eclipse fraction
- `figures/m2_area_sensitivity.png` — array area vs. recharge efficiency / EOL degradation / cell efficiency
- `figures/m2_ops_trade.png` — array area vs. communications duty and payload duty

## Baseline mission (illustrative)

Representative 3U-cubesat-class LEO Earth-observation mission — every
number is a stated engineering assumption, not a sourced commercial
hardware spec (see `docs/methodology.md` §6 for the full table and
rationale).

| metric | value |
|---|---|
| orbit period | 94.6 min |
| eclipse fraction | 0.356 |
| orbit-average power | 8.79 W |
| peak bus power | 14.50 W |
| total energy/orbit | 13.85 Wh |
| sunlight / eclipse energy | 9.47 Wh / 4.38 Wh |

## Solar array sizing (Milestone 2)

**Orbit-average spacecraft power is not the required solar-array
output.** The array only exists electrically during the sunlight arc
(60.9 of the 94.6-minute orbit); in that window it must power the
sunlight loads *and* generate enough surplus to fully recharge
whatever the eclipse arc consumed — through lossy conversion paths.
Naive sizing to `P_avg = 8.79 W` therefore undersizes the array.

| Quantity | Value |
|---|---:|
| Raw required array output (sunlight-only recharge equation) | **15.44 W** (1.76x naive `P_avg`) |
| Design array output (25% margin) | **19.30 W** |
| BOL / EOL usable power density | 347.1 / 295.0 W/m² |
| Required array area | **0.065 m²** |
| Energy closure | generated 19.60 Wh ≥ required 15.68 Wh (+25.0% margin) |

Strongest sensitivities: array area scales **exactly inversely** with
both cell efficiency and EOL degradation (`A ∝ 1/η_cell`, `A ∝ 1/f_EOL`,
verified to 1e-9), and rises monotonically as eclipse fraction grows
(0.040 m² at `f_e=0.20` → 0.060 m² at `f_e=0.45`). Payload duty is a
stronger array-area driver than communications duty, since the
payload's 14.5 W bus draw exceeds the downlink's 10.2 W.

See [`docs/solar_array_methodology.md`](docs/solar_array_methodology.md)
for the full derivation, and
[`results/figures/m2_eclipse_sensitivity.png`](results/figures/m2_eclipse_sensitivity.png) /
[`results/figures/m2_ops_trade.png`](results/figures/m2_ops_trade.png)
for the strongest figures.

## Engineering conventions

- SI base units throughout the core library (seconds, watts, joules);
  any other unit (Wh, minutes) carries an explicit suffix and is only
  produced at the reporting layer.
- All values are stated engineering assumptions unless a source is
  cited — no invented commercial hardware specs.
- Energies/averages are computed by exact analytic integration of the
  piecewise-constant schedule, never by sampling alone; sampled traces
  exist only for plotting and are cross-checked against the analytic
  result in tests.

## Roadmap

1. ✅ **Milestone 1** — operating modes, orbit/eclipse geometry, energy balance
2. ✅ **Milestone 2** — solar-array sizing and sunlight energy closure
3. ⏳ Milestone 3 — battery sizing
4. ⏳ Milestone 4+ — sensitivity analysis, margins, final report
