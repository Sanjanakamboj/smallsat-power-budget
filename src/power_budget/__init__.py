"""power_budget — spacecraft EPS sizing package.

Milestone 1 scope: deterministic power/energy accounting core.
    - operating-mode definitions (:mod:`power_budget.modes`)
    - orbit / eclipse geometry (:mod:`power_budget.orbit`)
    - mode timelines over one orbit (:mod:`power_budget.schedule`)
    - power-profile sampling and energy integration (:mod:`power_budget.energy`)
    - the top-level power-budget summary (:mod:`power_budget.budget`)

Unit convention: every public function/attribute uses SI base units
internally (seconds, watts, joules, kelvin, ...). Quantities that are
commonly reported in other units (watt-hours, minutes) carry an explicit
suffix (e.g. ``energy_wh``) or are produced only in reporting-layer code
(scripts/, docs/), never inside the core library.
"""

from power_budget.modes import Mode
from power_budget.orbit import OrbitGeometry
from power_budget.schedule import ScheduleEntry, OrbitSchedule
from power_budget.budget import PowerBudget, build_power_budget
from power_budget.solar import (
    SolarArrayConfig,
    SolarArraySizingResult,
    EnergyClosureResult,
    size_solar_array,
)
from power_budget.battery import (
    BatteryConfig,
    BatterySizingResult,
    RechargeClosureResult,
    SOCProfile,
    size_battery,
)

__all__ = [
    "Mode",
    "OrbitGeometry",
    "ScheduleEntry",
    "OrbitSchedule",
    "PowerBudget",
    "build_power_budget",
    "SolarArrayConfig",
    "SolarArraySizingResult",
    "EnergyClosureResult",
    "size_solar_array",
    "BatteryConfig",
    "BatterySizingResult",
    "RechargeClosureResult",
    "SOCProfile",
    "size_battery",
]

__version__ = "0.1.0"
