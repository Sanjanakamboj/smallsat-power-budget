import pytest

from power_budget.orbit import OrbitGeometry


def test_basic_geometry():
    o = OrbitGeometry(period_s=6000.0, eclipse_fraction=0.4)
    assert o.eclipse_duration_s == pytest.approx(2400.0)
    assert o.sunlight_duration_s == pytest.approx(3600.0)
    assert o.sunlight_start_s == 0.0
    assert o.sunlight_end_s == pytest.approx(3600.0)
    assert o.eclipse_start_s == pytest.approx(3600.0)
    assert o.eclipse_end_s == pytest.approx(6000.0)


def test_zero_eclipse_fraction_allowed():
    o = OrbitGeometry(period_s=6000.0, eclipse_fraction=0.0)
    assert o.eclipse_duration_s == 0.0
    assert o.sunlight_duration_s == pytest.approx(6000.0)


@pytest.mark.parametrize("period_s", [0.0, -100.0])
def test_rejects_nonpositive_period(period_s):
    with pytest.raises(ValueError):
        OrbitGeometry(period_s=period_s, eclipse_fraction=0.3)


@pytest.mark.parametrize("f", [-0.01, 1.0, 1.5])
def test_rejects_out_of_range_eclipse_fraction(f):
    with pytest.raises(ValueError):
        OrbitGeometry(period_s=6000.0, eclipse_fraction=f)


def test_phase_at():
    o = OrbitGeometry(period_s=6000.0, eclipse_fraction=0.4)
    assert o.phase_at(0.0) == "sunlight"
    assert o.phase_at(3599.9) == "sunlight"
    assert o.phase_at(3600.0) == "eclipse"
    assert o.phase_at(5999.9) == "eclipse"


def test_phase_at_wraps_modulo_period():
    o = OrbitGeometry(period_s=6000.0, eclipse_fraction=0.4)
    # one full orbit + 100 s should behave like t=100 s (sunlight)
    assert o.phase_at(6100.0) == o.phase_at(100.0) == "sunlight"
    # two orbits + into eclipse arc
    assert o.phase_at(2 * 6000.0 + 3700.0) == "eclipse"
