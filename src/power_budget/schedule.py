"""Mode timelines over one orbit.

An :class:`OrbitSchedule` is an ordered, gap-free, non-overlapping list
of :class:`ScheduleEntry` intervals that partitions exactly one orbital
period ``[0, period_s)``. Requiring full, exact coverage (rather than
allowing implicit "off" gaps) keeps the energy accounting unambiguous
and forces every second of the orbit to be attributed to a named mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from power_budget.modes import Mode

_TOL_S = 1e-6  # numerical tolerance for boundary/coverage comparisons, seconds


@dataclass(frozen=True)
class ScheduleEntry:
    """One contiguous span of a single operating mode within an orbit.

    Attributes
    ----------
    mode:
        The :class:`~power_budget.modes.Mode` active during this span.
    start_s:
        Start time within the orbit, seconds, measured from the start of
        the sunlit arc (see :mod:`power_budget.orbit`). Must be >= 0.
    end_s:
        End time within the orbit, seconds. Must be > start_s.
    """

    mode: Mode
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise ValueError(f"start_s must be >= 0, got {self.start_s!r}")
        if self.end_s <= self.start_s:
            raise ValueError(
                f"end_s ({self.end_s!r}) must be > start_s ({self.start_s!r})"
            )

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def energy_j(self) -> float:
        """Energy consumed during this span, joules (W * s)."""
        return self.mode.power_w * self.duration_s


@dataclass(frozen=True)
class OrbitSchedule:
    """A validated, full-coverage sequence of :class:`ScheduleEntry`.

    Entries must be supplied in chronological order, share a common
    ``orbit_period_s``, start at ``t = 0``, and tile the interval
    ``[0, orbit_period_s)`` exactly -- no gaps, no overlaps.
    """

    entries: tuple[ScheduleEntry, ...]
    orbit_period_s: float

    def __post_init__(self) -> None:
        if self.orbit_period_s <= 0:
            raise ValueError(
                f"orbit_period_s must be > 0, got {self.orbit_period_s!r}"
            )
        if not self.entries:
            raise ValueError("OrbitSchedule requires at least one entry")

        entries = list(self.entries)
        if entries[0].start_s > _TOL_S:
            raise ValueError(
                "Schedule must start at t=0, first entry starts at "
                f"{entries[0].start_s!r} s"
            )
        for prev, cur in zip(entries, entries[1:]):
            gap = cur.start_s - prev.end_s
            if abs(gap) > _TOL_S:
                kind = "gap" if gap > 0 else "overlap"
                raise ValueError(
                    f"Schedule has a {kind} of {abs(gap):.6g} s between "
                    f"{prev.mode.name!r} (ends {prev.end_s:.6g} s) and "
                    f"{cur.mode.name!r} (starts {cur.start_s:.6g} s)"
                )
        last_end = entries[-1].end_s
        if abs(last_end - self.orbit_period_s) > _TOL_S:
            raise ValueError(
                f"Schedule must cover the full orbit period "
                f"({self.orbit_period_s:.6g} s); last entry ends at "
                f"{last_end:.6g} s"
            )

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def total_duration_s(self) -> float:
        return sum(e.duration_s for e in self.entries)

    def mode_at(self, t_s: float) -> Mode:
        """Return the :class:`Mode` active at time ``t_s`` (wrapped mod period)."""
        t = t_s % self.orbit_period_s
        for e in self.entries:
            # half-open [start, end) except the very last entry, which is
            # closed at orbit_period_s so that t == period wraps to t == 0
            # rather than raising.
            if e.start_s <= t < e.end_s or (
                math.isclose(t, self.orbit_period_s, abs_tol=_TOL_S)
                and math.isclose(e.end_s, self.orbit_period_s, abs_tol=_TOL_S)
            ):
                return e.mode
        raise RuntimeError(f"No schedule entry covers t={t_s!r} (bug: coverage gap)")
