"""Orbit / eclipse geometry.

Milestone 1 treats eclipse fraction as a direct input (computed
elsewhere from orbit altitude, inclination, and beta angle in a later
milestone). The only geometric model needed here is the split of one
orbit period into a contiguous sunlight arc followed by a contiguous
eclipse arc.

Time convention
----------------
``t = 0`` is defined as the start of the sunlit arc (e.g. orbit-noon
node exit). The spacecraft is in sunlight for ``t in [0, t_sunlight_end)``
and in eclipse for ``t in [t_sunlight_end, period_s)``. This avoids any
wraparound arithmetic in schedule/energy code. A mission schedule is
free to place any operating mode at any time within the orbit; nothing
requires eclipse to align with any particular mode boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrbitGeometry:
    """One orbit's period and eclipse fraction.

    Attributes
    ----------
    period_s:
        Orbital period, seconds. Must be > 0.
    eclipse_fraction:
        Fraction of the orbital period spent in Earth's shadow (umbra),
        dimensionless, in [0, 1). 0 means a permanently sunlit orbit
        (e.g. dawn-dusk sun-synchronous); 1 is not physically reachable
        for a bound orbit and is rejected.
    """

    period_s: float
    eclipse_fraction: float

    def __post_init__(self) -> None:
        if self.period_s <= 0:
            raise ValueError(f"period_s must be > 0, got {self.period_s!r}")
        if not (0.0 <= self.eclipse_fraction < 1.0):
            raise ValueError(
                "eclipse_fraction must be in [0, 1), got "
                f"{self.eclipse_fraction!r}"
            )

    @property
    def eclipse_duration_s(self) -> float:
        """Length of the eclipse arc, seconds."""
        return self.period_s * self.eclipse_fraction

    @property
    def sunlight_duration_s(self) -> float:
        """Length of the sunlit arc, seconds."""
        return self.period_s - self.eclipse_duration_s

    @property
    def sunlight_start_s(self) -> float:
        return 0.0

    @property
    def sunlight_end_s(self) -> float:
        return self.sunlight_duration_s

    @property
    def eclipse_start_s(self) -> float:
        return self.sunlight_duration_s

    @property
    def eclipse_end_s(self) -> float:
        return self.period_s

    def phase_at(self, t_s: float) -> str:
        """Return ``"sunlight"`` or ``"eclipse"`` for a time within the orbit.

        ``t_s`` is wrapped modulo ``period_s`` so any time on the
        infinite timeline is accepted.
        """
        t_wrapped = t_s % self.period_s
        return "sunlight" if t_wrapped < self.sunlight_duration_s else "eclipse"
