import math

import pytest

from power_budget.modes import Mode, ModeSet


def test_mode_valid():
    m = Mode("nominal", 5.5, "housekeeping")
    assert m.power_w == 5.5
    assert m.name == "nominal"


def test_mode_rejects_negative_power():
    with pytest.raises(ValueError):
        Mode("bad", -1.0)


def test_mode_rejects_nan_power():
    with pytest.raises(ValueError):
        Mode("bad", math.nan)


def test_mode_rejects_empty_name():
    with pytest.raises(ValueError):
        Mode("", 1.0)
    with pytest.raises(ValueError):
        Mode("   ", 1.0)


def test_mode_zero_power_allowed():
    m = Mode("off", 0.0)
    assert m.power_w == 0.0


def test_mode_is_frozen():
    m = Mode("nominal", 5.5)
    with pytest.raises(Exception):
        m.power_w = 10.0  # type: ignore[misc]


def test_modeset_rejects_duplicates():
    with pytest.raises(ValueError):
        ModeSet((Mode("a", 1.0), Mode("a", 2.0)))


def test_modeset_by_name():
    ms = ModeSet((Mode("a", 1.0), Mode("b", 2.0)))
    assert ms.by_name("b").power_w == 2.0
    with pytest.raises(KeyError):
        ms.by_name("missing")
    assert len(ms) == 2
    assert {m.name for m in ms} == {"a", "b"}
