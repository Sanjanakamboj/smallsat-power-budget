"""Shared fixtures for the power_budget test suite."""

from __future__ import annotations

import pytest

from power_budget.modes import Mode
from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule, ScheduleEntry

# A representative 3U-cubesat-class LEO mission, used across several
# test modules. Values are illustrative engineering assumptions, not
# sourced hardware specs.
SAFE = Mode("safe", power_w=3.0, description="Safe mode: RX beacon only")
NOMINAL = Mode("nominal", power_w=5.5, description="Housekeeping / idle")
PAYLOAD = Mode("payload_imaging", power_w=12.0, description="Camera + processing")
DOWNLINK = Mode("downlink", power_w=9.0, description="S-band transmit")
CHARGING_ONLY = Mode("charging_only", power_w=4.0, description="Battery-priority charge")

ORBIT_PERIOD_S = 5760.0  # ~96 min, ~550 km LEO
ECLIPSE_FRACTION = 0.375  # ~36 min eclipse of a 96 min orbit


@pytest.fixture
def orbit() -> OrbitGeometry:
    return OrbitGeometry(period_s=ORBIT_PERIOD_S, eclipse_fraction=ECLIPSE_FRACTION)


@pytest.fixture
def simple_schedule(orbit: OrbitGeometry) -> OrbitSchedule:
    """A schedule with a single mode boundary that straddles the terminator.

    Sunlight arc: [0, 3600). Eclipse arc: [3600, 5760).
    Payload imaging runs [3000, 4200) -- 600 s in sunlight, 600 s in eclipse.
    """
    entries = (
        ScheduleEntry(NOMINAL, 0.0, 3000.0),
        ScheduleEntry(PAYLOAD, 3000.0, 4200.0),
        ScheduleEntry(DOWNLINK, 4200.0, 5000.0),
        ScheduleEntry(NOMINAL, 5000.0, ORBIT_PERIOD_S),
    )
    return OrbitSchedule(entries=entries, orbit_period_s=ORBIT_PERIOD_S)
