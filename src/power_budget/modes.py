"""Operating-mode definitions.

A ``Mode`` is a named electrical load state of the spacecraft bus
(e.g. Safe, Nominal/Housekeeping, Payload/Imaging, Downlink/Comms,
Charging). Milestone 1 treats each mode as drawing a single
representative average power for its duration -- transient/inrush
behavior is out of scope until a later milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mode:
    """A spacecraft operating mode and its representative bus load.

    Attributes
    ----------
    name:
        Short unique identifier, e.g. ``"safe"``, ``"payload_imaging"``.
    power_w:
        Representative average electrical power draw of the mode at the
        spacecraft bus, in watts. Must be >= 0.
    description:
        Free-text description of what the spacecraft is doing in this mode.
    """

    name: str
    power_w: float
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Mode.name must be a non-empty string")
        if self.power_w < 0:
            raise ValueError(
                f"Mode {self.name!r}: power_w must be >= 0, got {self.power_w!r}"
            )
        if not (self.power_w == self.power_w):  # NaN check
            raise ValueError(f"Mode {self.name!r}: power_w must not be NaN")


@dataclass(frozen=True)
class ModeSet:
    """A named, de-duplicated collection of :class:`Mode` objects."""

    modes: tuple[Mode, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        names = [m.name for m in self.modes]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"Duplicate mode names in ModeSet: {sorted(dupes)}")

    def by_name(self, name: str) -> Mode:
        for m in self.modes:
            if m.name == name:
                return m
        raise KeyError(f"No mode named {name!r} in ModeSet")

    def __iter__(self):
        return iter(self.modes)

    def __len__(self) -> int:
        return len(self.modes)
