import pytest

from power_budget.battery import BatteryConfig, size_battery
from power_budget.budget import build_power_budget
from power_budget.integrated import (
    EPSDesign,
    EPSMargins,
    compute_margins,
    eps_design_from_baseline,
    requirement_from_power_budget,
)
from power_budget.solar import SolarArrayConfig, size_solar_array

# ---------------------------------------------------------------------------
# EPSDesign validation
# ---------------------------------------------------------------------------


def _valid_kwargs(**overrides):
    kwargs = dict(
        array_area_m2=0.065,
        array_bol_density_w_m2=347.0,
        array_eol_density_w_m2=295.0,
        eta_sun_path=0.90,
        eta_recharge_path=0.85,
        battery_capacity_bol_wh=30.0,
        battery_f_cap_eol=0.80,
        dod_max=0.25,
        eta_discharge=0.95,
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_design_constructs():
    design = EPSDesign(**_valid_kwargs())
    assert design.array_area_m2 == 0.065


@pytest.mark.parametrize("field", ["array_area_m2", "battery_capacity_bol_wh",
                                     "array_bol_density_w_m2", "array_eol_density_w_m2"])
def test_design_rejects_nonpositive_physical_fields(field):
    with pytest.raises(ValueError):
        EPSDesign(**_valid_kwargs(**{field: 0.0}))
    with pytest.raises(ValueError):
        EPSDesign(**_valid_kwargs(**{field: -1.0}))


@pytest.mark.parametrize("field", ["eta_sun_path", "eta_recharge_path", "battery_f_cap_eol",
                                     "eta_discharge", "dod_max"])
@pytest.mark.parametrize("bad", [0.0, -0.1, 1.1])
def test_design_rejects_out_of_range_efficiencies(field, bad):
    with pytest.raises(ValueError):
        EPSDesign(**_valid_kwargs(**{field: bad}))


def test_array_power_bol_eol_properties():
    design = EPSDesign(**_valid_kwargs(array_area_m2=0.1, array_bol_density_w_m2=300.0, array_eol_density_w_m2=250.0))
    assert design.array_power_bol_w == pytest.approx(30.0)
    assert design.array_power_eol_w == pytest.approx(25.0)


def test_battery_capacity_eol_properties():
    design = EPSDesign(**_valid_kwargs(battery_capacity_bol_wh=40.0, battery_f_cap_eol=0.75, dod_max=0.3))
    assert design.battery_capacity_eol_wh == pytest.approx(30.0)
    assert design.battery_capacity_eol_j == pytest.approx(30.0 * 3600)
    assert design.battery_usable_energy_eol_j == pytest.approx(0.3 * 30.0 * 3600)


# ---------------------------------------------------------------------------
# Construction from M2/M3 baseline (no re-derivation)
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_design_inputs(simple_schedule, orbit):
    pb = build_power_budget(simple_schedule, orbit)
    solar_result = size_solar_array(pb, SolarArrayConfig())
    battery_result = size_battery(pb, solar_result, BatteryConfig())
    return pb, solar_result, battery_result


def test_eps_design_from_baseline_matches_m2_m3(baseline_design_inputs):
    pb, solar_result, battery_result = baseline_design_inputs
    design = eps_design_from_baseline(solar_result, battery_result)
    assert design.array_area_m2 == pytest.approx(solar_result.area_m2)
    assert design.array_bol_density_w_m2 == pytest.approx(solar_result.bol_density_w_m2)
    assert design.array_eol_density_w_m2 == pytest.approx(solar_result.eol_density_w_m2)
    assert design.battery_capacity_bol_wh == pytest.approx(battery_result.selected_capacity_wh)
    assert design.dod_max == pytest.approx(battery_result.config.dod_max)


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------


def test_requirement_from_power_budget(baseline_design_inputs):
    pb, _, _ = baseline_design_inputs
    req = requirement_from_power_budget(pb)
    assert req.t_sun_s == pytest.approx(pb.phase_energy["sunlight"].duration_s)
    assert req.e_sun_j == pytest.approx(pb.phase_energy["sunlight"].energy_j)
    assert req.e_eclipse_j == pytest.approx(pb.phase_energy["eclipse"].energy_j)
    assert req.peak_load_w == pytest.approx(pb.peak_power_w)
    assert req.orbit_energy_j == pytest.approx(pb.total_energy_j)


# ---------------------------------------------------------------------------
# Margins
# ---------------------------------------------------------------------------


def test_compute_margins_matches_m2_at_nominal_design(baseline_design_inputs):
    """At the exact M2/M3-selected design, the solar/array-power margins
    computed here should reproduce M2's own design margin (both
    represent the array's designed EOL surplus over the raw
    requirement)."""
    pb, solar_result, battery_result = baseline_design_inputs
    design = eps_design_from_baseline(solar_result, battery_result)
    req = requirement_from_power_budget(pb)
    margins = compute_margins(design, req, t_recharge_s=None)

    assert isinstance(margins, EPSMargins)
    assert margins.solar_energy_margin == pytest.approx(solar_result.config.design_margin, rel=1e-6)
    assert margins.array_power_margin == pytest.approx(solar_result.config.design_margin, rel=1e-6)
    assert margins.recharge_time_margin == float("inf")  # t_recharge_s=None


def test_compute_margins_rejects_zero_sunlight_duration(baseline_design_inputs):
    pb, solar_result, battery_result = baseline_design_inputs
    design = eps_design_from_baseline(solar_result, battery_result)
    req = requirement_from_power_budget(pb)
    bad_req = req.__class__(t_sun_s=0.0, e_sun_j=req.e_sun_j, e_eclipse_j=req.e_eclipse_j,
                             peak_load_w=req.peak_load_w, orbit_energy_j=req.orbit_energy_j)
    with pytest.raises(ValueError):
        compute_margins(design, bad_req, t_recharge_s=None)


def test_larger_array_increases_solar_and_power_margins(baseline_design_inputs):
    """A strictly larger array (all else equal) must not decrease solar
    feasibility margins."""
    pb, solar_result, battery_result = baseline_design_inputs
    base_design = eps_design_from_baseline(solar_result, battery_result)
    req = requirement_from_power_budget(pb)
    base_margins = compute_margins(base_design, req, None)

    bigger = EPSDesign(
        array_area_m2=base_design.array_area_m2 * 1.5,
        array_bol_density_w_m2=base_design.array_bol_density_w_m2,
        array_eol_density_w_m2=base_design.array_eol_density_w_m2,
        eta_sun_path=base_design.eta_sun_path,
        eta_recharge_path=base_design.eta_recharge_path,
        battery_capacity_bol_wh=base_design.battery_capacity_bol_wh,
        battery_f_cap_eol=base_design.battery_f_cap_eol,
        dod_max=base_design.dod_max,
        eta_discharge=base_design.eta_discharge,
    )
    bigger_margins = compute_margins(bigger, req, None)
    assert bigger_margins.solar_energy_margin > base_margins.solar_energy_margin
    assert bigger_margins.array_power_margin > base_margins.array_power_margin


def test_larger_battery_increases_battery_margin_only(baseline_design_inputs):
    """A strictly larger battery (all else equal) must not decrease the
    battery energy margin, and must not change the solar/array-power
    margins (those depend only on the array)."""
    pb, solar_result, battery_result = baseline_design_inputs
    base_design = eps_design_from_baseline(solar_result, battery_result)
    req = requirement_from_power_budget(pb)
    base_margins = compute_margins(base_design, req, None)

    bigger_batt = EPSDesign(
        array_area_m2=base_design.array_area_m2,
        array_bol_density_w_m2=base_design.array_bol_density_w_m2,
        array_eol_density_w_m2=base_design.array_eol_density_w_m2,
        eta_sun_path=base_design.eta_sun_path,
        eta_recharge_path=base_design.eta_recharge_path,
        battery_capacity_bol_wh=base_design.battery_capacity_bol_wh * 1.5,
        battery_f_cap_eol=base_design.battery_f_cap_eol,
        dod_max=base_design.dod_max,
        eta_discharge=base_design.eta_discharge,
    )
    bigger_margins = compute_margins(bigger_batt, req, None)
    assert bigger_margins.battery_energy_margin > base_margins.battery_energy_margin
    assert bigger_margins.solar_energy_margin == pytest.approx(base_margins.solar_energy_margin)
    assert bigger_margins.array_power_margin == pytest.approx(base_margins.array_power_margin)


def test_recharge_time_margin_formula():
    from power_budget.integrated import compute_margins, MissionRequirement

    design = EPSDesign(**_valid_kwargs())
    req = MissionRequirement(t_sun_s=1000.0, e_sun_j=1000.0, e_eclipse_j=500.0, peak_load_w=10.0, orbit_energy_j=2000.0)
    margins = compute_margins(design, req, t_recharge_s=250.0)
    assert margins.recharge_time_margin == pytest.approx(4.0)
