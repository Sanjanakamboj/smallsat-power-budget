# Milestone 3 — Battery Sizing

Baseline 3U-cubesat-class LEO mission, reusing the Milestone-1 load model and Milestone-2 array sizing unchanged.

## Sizing table

| Quantity | Value |
|---|---:|
| Eclipse load energy | 4.38 Wh |
| Discharge efficiency (eta_d) | 0.95 |
| Battery withdrawal | 4.61 Wh |
| Max DoD | 0.25 |
| Raw capacity | 18.46 Wh |
| Capacity margin (SF_C) | 1.25 |
| EOL required capacity | 23.07 Wh |
| EOL retention (f_cap,EOL) | 0.80 |
| Minimum BOL nameplate | 28.84 Wh |
| Selected design capacity | 30.0 Wh |
| Actual DoD at selected capacity | 15.4% |
| Baseline minimum SOC | 84.6% |
| Recharge time / utilization | 42.3 min (69.4% of sunlight) |

## Recharge closure (M2 <-> M3 consistency)

Available sunlight recharge (via M2's eta_recharge_path): **7.72 Wh**  
Required (battery-side withdrawal): **4.61 Wh**  
Margin: **67.2%**  
Closes: **True**

