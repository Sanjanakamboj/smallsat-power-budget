"""Power-profile sampling and energy integration.

All energies here are computed by exact analytic integration of the
piecewise-constant power profile (sum of power * duration over each
constant-power sub-interval) -- not by numerical quadrature of a
sampled trace. :func:`power_profile` exists only to produce a plotting
trace; it must never be the source of a reported energy or average-power
number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from power_budget.orbit import OrbitGeometry
from power_budget.schedule import OrbitSchedule

_TOL_S = 1e-6


def power_profile(
    schedule: OrbitSchedule, dt_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Sample the piecewise-constant bus-power profile for plotting.

    Parameters
    ----------
    schedule:
        The orbit's mode timeline.
    dt_s:
        Sample spacing, seconds. Must be > 0 and << the shortest mode
        duration for the plot to resolve every transition.

    Returns
    -------
    (t_s, power_w):
        ``t_s`` is a 1-D array of sample times covering
        ``[0, orbit_period_s]`` inclusive of the final endpoint so the
        profile visibly closes the orbit; ``power_w`` is the bus power
        at each sample time (right-hand value at any transition sample,
        i.e. the mode that is *starting* at that instant).
    """
    if dt_s <= 0:
        raise ValueError(f"dt_s must be > 0, got {dt_s!r}")

    n_steps = int(np.ceil(schedule.orbit_period_s / dt_s))
    t_s = np.linspace(0.0, schedule.orbit_period_s, n_steps + 1)
    power_w = np.empty_like(t_s)
    for i, t in enumerate(t_s):
        # Evaluate just inside the orbit for the final sample so it
        # reports the last active mode rather than wrapping to t=0.
        t_query = t if t < schedule.orbit_period_s else t - _TOL_S
        power_w[i] = schedule.mode_at(t_query).power_w
    return t_s, power_w


def peak_power_w(schedule: OrbitSchedule) -> float:
    """Peak (maximum) bus power demand over the orbit, watts."""
    return max(e.mode.power_w for e in schedule.entries)


def orbit_average_power_w(schedule: OrbitSchedule) -> float:
    """Orbit-average bus power, watts: total energy / orbit period."""
    total_energy_j = sum(e.energy_j for e in schedule.entries)
    return total_energy_j / schedule.orbit_period_s


def total_energy_j(schedule: OrbitSchedule) -> float:
    """Total electrical energy consumed over one orbit, joules."""
    return sum(e.energy_j for e in schedule.entries)


@dataclass(frozen=True)
class PhaseEnergy:
    """Energy and average power accounting for one orbit phase."""

    duration_s: float
    energy_j: float

    @property
    def average_power_w(self) -> float:
        return self.energy_j / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def energy_wh(self) -> float:
        return self.energy_j / 3600.0


def energy_by_phase(
    schedule: OrbitSchedule, orbit: OrbitGeometry
) -> dict[str, PhaseEnergy]:
    """Split schedule energy into sunlight vs. eclipse contributions.

    Handles mode spans that straddle the sunlight/eclipse terminator by
    sweeping every boundary (schedule-entry edges union the eclipse
    boundary) and attributing each resulting sub-interval to the phase
    and mode active at its midpoint.

    Returns
    -------
    dict with keys ``"sunlight"`` and ``"eclipse"`` mapping to
    :class:`PhaseEnergy`.
    """
    if abs(schedule.orbit_period_s - orbit.period_s) > _TOL_S:
        raise ValueError(
            "schedule.orbit_period_s "
            f"({schedule.orbit_period_s!r}) must match orbit.period_s "
            f"({orbit.period_s!r})"
        )

    boundaries = {0.0, orbit.period_s, orbit.eclipse_start_s}
    for e in schedule.entries:
        boundaries.add(e.start_s)
        boundaries.add(e.end_s)
    sorted_bounds = sorted(boundaries)

    energy_by_key = {"sunlight": 0.0, "eclipse": 0.0}
    duration_by_key = {"sunlight": 0.0, "eclipse": 0.0}

    for a, b in zip(sorted_bounds, sorted_bounds[1:]):
        span = b - a
        if span <= _TOL_S:
            continue
        mid = 0.5 * (a + b)
        power_w = schedule.mode_at(mid).power_w
        phase = orbit.phase_at(mid)
        duration_by_key[phase] += span
        energy_by_key[phase] += power_w * span

    return {
        phase: PhaseEnergy(duration_s=duration_by_key[phase], energy_j=energy_by_key[phase])
        for phase in ("sunlight", "eclipse")
    }
