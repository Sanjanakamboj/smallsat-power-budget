# GNC-05 — Smallsat Power Budget

A coding-focused spacecraft electrical power system (EPS) sizing
portfolio project. Converts mission operating modes, eclipse fraction,
and duty cycle into a defensible **power budget, solar-array
requirement, and battery requirement**, built as a reusable, tested
Python package rather than a one-off notebook.

## Status

**Milestone 1 — EPS Foundations, Operating Modes & Energy Balance**
(complete). See [`docs/methodology.md`](docs/methodology.md) for the
full write-up. Solar-array sizing and battery sizing are later
milestones and are not yet implemented.

## What's here

```
src/power_budget/     Core package (deterministic power/energy accounting)
  modes.py              Operating-mode definitions (Mode, ModeSet)
  orbit.py               Orbit period / eclipse-fraction geometry
  schedule.py            Full-coverage mode timeline over one orbit
  energy.py               Power-profile sampling + analytic energy integration
  budget.py                Per-mode power-budget table + orbit summary
tests/                 pytest suite (unit tests + invariant checks)
scripts/
  mission_baseline.py    Baseline mission definition (orbit, modes, schedule)
  run_power_budget.py    Runs the analysis, writes table + figures
docs/methodology.md    Full methodology, equations, and assumptions
results/               Generated table (CSV), summary (txt), figures (PNG)
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                        # run the test suite
python scripts/run_power_budget.py   # regenerate table + figures
```

Outputs land in `results/`:
- `power_budget_table.csv` — per-mode power/duty-cycle/energy table
- `power_budget_summary.txt` — orbit-average power, peak power, sunlight/eclipse energy
- `figures/power_profile.png` — instantaneous bus power over one orbit
- `figures/mode_energy.png` — per-mode energy contribution

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
2. ⏳ Milestone 2 — solar-array sizing
3. ⏳ Milestone 3 — battery sizing
4. ⏳ Milestone 4+ — sensitivity analysis, margins, final report
