"""Baseline mission definition for the GNC-05 smallsat power-budget study.

Representative 3U-cubesat-class LEO Earth-observation mission. All
numbers are illustrative engineering assumptions (not sourced hardware
specs) chosen to be representative of a small imaging satellite:

  - ~500 km circular sun-synchronous-like LEO -> ~94.6 min period
  - eclipse fraction ~35.6% (representative of a ~500 km orbit away
    from the terminator-locked dawn/dusk case)
  - one imaging + one downlink pass per orbit, remainder in nominal
    housekeeping / idle

This module is imported by scripts/run_power_budget.py and by the
figure-generation code so the mission definition lives in exactly one
place.
"""

from __future__ import annotations

from power_budget.modes import Mode
from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule, ScheduleEntry

# ---------------------------------------------------------------------------
# Orbit
# ---------------------------------------------------------------------------
ORBIT = OrbitGeometry(period_s=5676.0, eclipse_fraction=0.356)

# ---------------------------------------------------------------------------
# Operating modes (representative bus power draws, watts)
# ---------------------------------------------------------------------------
SAFE = Mode("safe", power_w=3.2, description="Safe mode: beacon RX + minimal ADCS")
NOMINAL = Mode(
    "nominal", power_w=6.8, description="Housekeeping: OBC, ADCS, RX, thermal"
)
PAYLOAD_IMAGING = Mode(
    "payload_imaging",
    power_w=14.5,
    description="Camera + onboard image processing, ADCS pointing",
)
DOWNLINK = Mode(
    "downlink", power_w=10.2, description="S-band TX + OBC + ADCS pointing"
)
DETUMBLE = Mode(
    "detumble", power_w=4.5, description="B-dot detumble control (contingency)"
)

MODES = (SAFE, NOMINAL, PAYLOAD_IMAGING, DOWNLINK, DETUMBLE)

# ---------------------------------------------------------------------------
# Baseline nominal-operations schedule (one representative orbit)
# ---------------------------------------------------------------------------
# t=0 is the start of the sunlit arc. Sunlight: [0, sunlight_end_s).
# Eclipse: [sunlight_end_s, period_s).
#
# Timeline:
#   0        -> 1200 s   nominal housekeeping (post-eclipse checkout)
#   1200     -> 2400 s   payload imaging pass (in sunlight, mid-pass)
#   2400     -> sun_end  nominal housekeeping
#   sun_end  -> +900 s   nominal housekeeping continues into eclipse
#                        (ground-station downlink scheduled near eclipse exit)
#   ...      -> period   downlink pass, then nominal to close the orbit
_SUN_END = ORBIT.sunlight_end_s  # ~3650.4 s for the baseline geometry

BASELINE_SCHEDULE = OrbitSchedule(
    entries=(
        ScheduleEntry(NOMINAL, 0.0, 1200.0),
        ScheduleEntry(PAYLOAD_IMAGING, 1200.0, 2400.0),
        ScheduleEntry(NOMINAL, 2400.0, _SUN_END + 500.0),
        ScheduleEntry(DOWNLINK, _SUN_END + 500.0, _SUN_END + 1100.0),
        ScheduleEntry(NOMINAL, _SUN_END + 1100.0, ORBIT.period_s),
    ),
    orbit_period_s=ORBIT.period_s,
)
