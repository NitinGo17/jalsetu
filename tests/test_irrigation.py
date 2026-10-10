"""
Engine tests for JalSetu. These cover the required edge cases:
zero rainfall, rainfall exceeding demand, zero/invalid area, missing weather
variables, insufficient available water, unit conversions, normal conditions,
and determinism.
"""

import pytest

from backend.irrigation import (
    MM_PER_HA_TO_LITRES,
    RECOMMENDATION_INSPECT,
    RECOMMENDATION_IRRIGATE,
    RECOMMENDATION_WAIT,
    FieldInput,
    WeatherInput,
    calculate,
    litres_to_mm,
    mm_to_litres,
)


def field(**kw):
    base = dict(
        crop_id="wheat",
        growth_stage="flowering",
        soil_type="loamy",
        area_ha=1.0,
        irrigation_method="drip",
        available_water_l=100000,
        field_name="Test field",
    )
    base.update(kw)
    return FieldInput(**base)


def weather(**kw):
    base = dict(et0_mm=6.0, rainfall_mm=0.0, source="test", label="test")
    base.update(kw)
    return WeatherInput(**base)


# --- Unit conversions --------------------------------------------------------
def test_mm_to_litres_conversion():
    assert mm_to_litres(1, 1) == 10000
    assert mm_to_litres(1, 2) == 20000
    assert mm_to_litres(4, 1) == 40000
    assert mm_to_litres(0, 5) == 0
    assert MM_PER_HA_TO_LITRES == 10000


def test_litres_to_mm_roundtrip():
    assert litres_to_mm(40000, 1) == pytest.approx(4.0)
    assert litres_to_mm(20000, 2) == pytest.approx(1.0)
    assert litres_to_mm(1000, 0) == 0.0


# --- Normal condition --------------------------------------------------------
def test_normal_irrigation_conditions():
    # ETc = 6.0 * 1.15 = 6.9 mm; no rain -> NIR = 6.9 mm
    res = calculate(field(), weather(et0_mm=6.0, rainfall_mm=0.0))
    m = res["metrics"]
    assert res["recommendation"] == RECOMMENDATION_IRRIGATE
    assert m["crop_water_demand_mm"] == pytest.approx(6.9)
    assert m["net_irrigation_mm"] == pytest.approx(6.9)
    # drip efficiency 0.90 -> gross = 6.9 / 0.9
    assert m["gross_irrigation_mm"] == pytest.approx(6.9 / 0.90, abs=0.01)
    assert m["net_volume_l"] == pytest.approx(69000)
    assert m["water_status"] == "sufficient"


# --- Zero rainfall -----------------------------------------------------------
def test_zero_rainfall_means_no_effective_rain():
    res = calculate(field(), weather(et0_mm=5.0, rainfall_mm=0.0))
    assert res["breakdown"]["effective_rainfall_mm"] == 0.0
    assert res["metrics"]["net_irrigation_mm"] == pytest.approx(5.0 * 1.15)
    assert res["recommendation"] == RECOMMENDATION_IRRIGATE


# --- Rainfall exceeding demand ----------------------------------------------
def test_rainfall_exceeding_demand_is_capped_not_double_counted():
    # ETc = 5 * 1.15 = 5.75 mm; rain 20 mm -> effective capped at 5.75, NIR = 0
    res = calculate(field(), weather(et0_mm=5.0, rainfall_mm=20.0))
    b = res["breakdown"]
    assert b["effective_rainfall_mm"] == pytest.approx(5.75)
    assert b["net_irrigation_mm"] == 0.0
    assert res["metrics"]["net_volume_l"] == 0
    assert res["recommendation"] == RECOMMENDATION_WAIT


def test_partial_rainfall_reduces_requirement():
    # ETc = 5.75; rain 2 mm -> NIR = 3.75
    res = calculate(field(), weather(et0_mm=5.0, rainfall_mm=2.0))
    assert res["breakdown"]["effective_rainfall_mm"] == pytest.approx(2.0)
    assert res["metrics"]["net_irrigation_mm"] == pytest.approx(3.75)
    assert res["recommendation"] == RECOMMENDATION_IRRIGATE


# --- Zero / invalid area -----------------------------------------------------
def test_zero_area_is_rejected_as_more_data_needed():
    res = calculate(field(area_ha=0), weather())
    assert res["recommendation"] == RECOMMENDATION_INSPECT
    assert res["metrics"]["net_volume_l"] is None
    assert any("area" in r.lower() for r in res["reasons"])


def test_negative_area_is_rejected():
    res = calculate(field(area_ha=-1.0), weather())
    assert res["recommendation"] == RECOMMENDATION_INSPECT
    assert res["metrics"]["net_volume_l"] is None


# --- Missing weather variables ----------------------------------------------
def test_missing_et0_needs_more_data():
    res = calculate(field(), weather(et0_mm=None))
    assert res["recommendation"] == RECOMMENDATION_INSPECT
    assert any("et0" in r.lower() for r in res["reasons"])


def test_missing_rainfall_defaults_to_zero_with_warning():
    res = calculate(field(), weather(et0_mm=6.0, rainfall_mm=None))
    assert res["recommendation"] == RECOMMENDATION_IRRIGATE
    assert res["breakdown"]["forecast_rainfall_mm"] == 0.0
    assert any("rainfall" in w.lower() for w in res["warnings"])


# --- Insufficient available water -------------------------------------------
def test_insufficient_available_water_flags_inspect_and_warning():
    # ETc 6.9 mm over 1 ha, drip -> gross 7.67 mm -> ~76,667 L needed.
    res = calculate(field(available_water_l=10000), weather(et0_mm=6.0, rainfall_mm=0.0))
    assert res["recommendation"] == RECOMMENDATION_INSPECT
    assert res["metrics"]["water_status"] == "insufficient"
    assert res["metrics"]["deficit_l"] > 0
    assert any("below the gross requirement" in w for w in res["warnings"])


def test_sufficient_available_water_irrigates():
    res = calculate(field(available_water_l=100000), weather(et0_mm=6.0, rainfall_mm=0.0))
    assert res["recommendation"] == RECOMMENDATION_IRRIGATE
    assert res["metrics"]["water_status"] == "sufficient"


# --- Unknown crop / stage / method ------------------------------------------
def test_unknown_crop_needs_more_data():
    res = calculate(field(crop_id="dragonfruit"), weather())
    assert res["recommendation"] == RECOMMENDATION_INSPECT


def test_unknown_growth_stage_needs_more_data():
    res = calculate(field(growth_stage="photosynthesis"), weather())
    assert res["recommendation"] == RECOMMENDATION_INSPECT


def test_unknown_irrigation_method_needs_more_data():
    res = calculate(field(irrigation_method="magic"), weather())
    assert res["recommendation"] == RECOMMENDATION_INSPECT


# --- Area scaling ------------------------------------------------------------
def test_area_scales_volume_linearly():
    r1 = calculate(field(area_ha=1.0), weather(et0_mm=5.0, rainfall_mm=0.0))
    r2 = calculate(field(area_ha=2.5), weather(et0_mm=5.0, rainfall_mm=0.0))
    assert r2["metrics"]["net_volume_l"] == pytest.approx(r1["metrics"]["net_volume_l"] * 2.5)


# --- Determinism -------------------------------------------------------------
def test_same_inputs_produce_identical_results():
    a = calculate(field(), weather(et0_mm=5.5, rainfall_mm=1.2))
    b = calculate(field(), weather(et0_mm=5.5, rainfall_mm=1.2))
    assert a == b


# --- Internal consistency ----------------------------------------------------
def test_internally_consistent_breakdown():
    res = calculate(field(area_ha=1.0), weather(et0_mm=6.0, rainfall_mm=0.0))
    b = res["breakdown"]
    # ETc = ET0 * Kc
    assert b["crop_water_demand_mm"] == pytest.approx(b["et0_mm"] * b["kc"], abs=0.01)
    # NIR = ETc - Pe
    assert b["net_irrigation_mm"] == pytest.approx(
        b["crop_water_demand_mm"] - b["effective_rainfall_mm"], abs=0.01
    )
    # GIR = NIR / efficiency
    assert b["gross_irrigation_mm"] == pytest.approx(
        b["net_irrigation_mm"] / b["irrigation_efficiency"], abs=0.01
    )
    # Volume = depth * area * 10000
    assert b["net_volume_l"] == pytest.approx(
        b["net_irrigation_mm"] * b["area_ha"] * 10000, abs=1
    )
