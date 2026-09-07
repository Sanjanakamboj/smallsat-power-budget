# Milestone 2 — Solar Array Sizing

Baseline 3U-cubesat-class LEO mission, reusing the Milestone-1 load model unchanged. All quantities in SI unless labeled.

## Sizing table

| Quantity | Raw | Design/EOL |
|---|---:|---:|
| Sunlight duration | 60.9 min | 60.9 min |
| Sunlight load energy | 9.47 Wh | — |
| Eclipse load energy | 4.38 Wh | — |
| Required recharge energy (raw-equiv.) | 15.68 Wh | — |
| Required array output | 15.44 W | 19.30 W |
| Usable array power density | 347.1 W/m² (BOL) | 295.0 W/m² (EOL) |
| Required area | — | 0.065 m² |
| Naive avg-power estimate | 8.79 W | — |
| Raw / naive-avg ratio | 1.76x | — |

## Assumed efficiency / degradation factors

| Factor | Value | Meaning |
|---|---:|---|
| S0 (solar constant) | 1361 W/m² | representative, fixed, 1 AU |
| eta_cell (BOL PV efficiency) | 0.30 | representative multi-junction cell |
| f_array (incidence/packing/utilization) | 0.85 | single lumped derating factor |
| f_EOL (end-of-life degradation) | 0.85 | radiation + thermal-cycling loss |
| eta_sun_path (array-to-sunlight-load path) | 0.90 | regulation + harness |
| eta_recharge_path (eclipse recharge path) | 0.85 | battery charge-conversion |
| SF_P (design margin) | 1.25 | 25% design/load-growth margin |

## Energy closure

Generated (design power x sunlight duration): **19.60 Wh**  
Required (raw-equivalent, unity margin): **15.68 Wh**  
Residual margin: **25.0%**  
Closes: **True**

