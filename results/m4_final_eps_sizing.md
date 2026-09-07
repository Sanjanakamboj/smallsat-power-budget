# Milestone 4 — Final Integrated EPS Sizing

Baseline 3U-cubesat-class LEO mission, reusing the Milestone 1-3 load, solar, and battery models unchanged. Final hardware selected after deterministic robust-corner and Monte Carlo robustness evaluation.

## Final EPS sizing table

| Quantity | Requirement | Selected capability | Margin/status |
|---|---:|---:|---:|
| Peak load | 14.50 W | 25.07 W (array EOL) | 1.73x |
| Orbit energy | 13.85 Wh | — | closes (M1/M2) |
| Eclipse battery withdrawal | 4.61 Wh | 7.00 Wh (usable @ DoD_max, EOL) | 1.52x |
| Array area | 0.0654 m² (M2 analytical min) | 0.0850 m² (selected) | +30% |
| EOL array output | 19.30 W (min design) | 25.07 W | — |
| Battery BOL capacity | 30.0 Wh (M3 selected min) | 35.0 Wh (selected) | +17% |
| Battery EOL capacity | — | 28.00 Wh | — |
| Max DoD | 0.25 | 0.165 (nominal actual) | pass |
| Recharge time | 18.6 min | 18.6 min of 60.9 min sunlight | 3.28x |
| Monte Carlo closure | — | 99.99% | 95% CI [99.94%, 100.00%] |
| Robust corner | — | PASS | — |

## Nominal margins (final design)

- Solar (recharge closure) margin: **1.624x**
- Array power margin: **1.624x**
- Battery energy margin: **1.517x**
- Recharge-time margin: **3.277x**

