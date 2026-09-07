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

# ---------------------------------------------------------------------------
# Schedule generator (Milestone 2: mission-operations duty sensitivities)
# ---------------------------------------------------------------------------
# Reuses the same modes/powers/orbit as the frozen M1 baseline above; only
# varies how long the payload-imaging and downlink spans last, with the
# remainder of the orbit filled by nominal housekeeping. Calling this with
# the default arguments reproduces BASELINE_SCHEDULE exactly -- it is a
# strict generalization, not a redefinition, of the accepted M1 load model.
_PRE_IMAGING_S = 1200.0  # nominal housekeeping before the imaging pass starts
_DOWNLINK_START_S = _SUN_END + 500.0  # fixed downlink-pass start time, s


def build_schedule(
    payload_duration_s: float = 1200.0,
    downlink_duration_s: float = 600.0,
    orbit: OrbitGeometry = ORBIT,
) -> OrbitSchedule:
    """Build a mission schedule with configurable payload/downlink duty.

    All other timeline choices (imaging start time, downlink start
    time, mode power draws, orbit geometry) are held fixed at their M1
    baseline values so that varying ``payload_duration_s`` /
    ``downlink_duration_s`` isolates the effect of mission-operations
    duty cycle, not a change to the underlying load model.
    """
    imaging_end_s = _PRE_IMAGING_S + payload_duration_s
    downlink_end_s = _DOWNLINK_START_S + downlink_duration_s
    if imaging_end_s > _DOWNLINK_START_S:
        raise ValueError(
            f"payload_duration_s={payload_duration_s!r} s makes the imaging "
            f"pass (ends {imaging_end_s:.1f} s) overlap the downlink pass "
            f"(starts {_DOWNLINK_START_S:.1f} s)"
        )
    if downlink_end_s > orbit.period_s:
        raise ValueError(
            f"downlink_duration_s={downlink_duration_s!r} s makes the "
            f"downlink pass (ends {downlink_end_s:.1f} s) exceed the orbit "
            f"period ({orbit.period_s:.1f} s)"
        )

    # A payload_duration_s or downlink_duration_s of 0 (used by the M2
    # duty-cycle sweeps) collapses that span to zero length; drop such
    # spans and coalesce the now-adjacent nominal blocks so the result
    # is still a valid, gap-free, non-degenerate OrbitSchedule.
    raw_spans = [
        (NOMINAL, 0.0, _PRE_IMAGING_S),
        (PAYLOAD_IMAGING, _PRE_IMAGING_S, imaging_end_s),
        (NOMINAL, imaging_end_s, _DOWNLINK_START_S),
        (DOWNLINK, _DOWNLINK_START_S, downlink_end_s),
        (NOMINAL, downlink_end_s, orbit.period_s),
    ]
    spans = [s for s in raw_spans if s[2] - s[1] > 1e-9]

    coalesced: list[tuple[Mode, float, float]] = []
    for mode, start, end in spans:
        if coalesced and coalesced[-1][0] is mode and abs(coalesced[-1][2] - start) < 1e-6:
            prev_mode, prev_start, _ = coalesced[-1]
            coalesced[-1] = (prev_mode, prev_start, end)
        else:
            coalesced.append((mode, start, end))

    entries = tuple(ScheduleEntry(m, s, e) for m, s, e in coalesced)
    return OrbitSchedule(entries=entries, orbit_period_s=orbit.period_s)
