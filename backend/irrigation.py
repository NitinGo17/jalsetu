"""
irrigation.py
-------------
The JalSetu irrigation decision engine.

This module is deliberately free of web-framework code, I/O and randomness:
it is a pure function of its inputs, which makes it deterministic and directly
testable. The same inputs always produce the same result.

MODEL (simplified, and stated as such everywhere it is used)
------------------------------------------------------------
1. Crop water demand (crop evapotranspiration), one day:

       ETc = ET0 x Kc            [mm/day]

   ET0 is the reference evapotranspiration (from Open-Meteo), Kc is the
   crop coefficient for the chosen crop and growth stage.

2. Effective rainfall for the planning day:

       Pe = min(P, ETc)          [mm]

   where P is forecast rainfall. Rainfall beyond the day's demand is treated
   as lost to runoff or deep percolation in this simplified daily model. This
   cap is the single place rainfall is applied, so rainfall is never
   subtracted twice.

3. Net irrigation requirement (depth):

       NIR = max(0, ETc - Pe)    [mm]

4. Gross applied water (depth), accounting for irrigation efficiency:

       GIR = NIR / efficiency    [mm]

5. Volume, using 1 mm of depth over 1 hectare = 10,000 litres:

       litres = depth_mm x area_ha x 10,000

WHAT THIS MODEL IS NOT
----------------------
- It is not a soil-moisture measurement. Weather forecasts are demand-side
  estimates, not readings from the field.
- It does not model soil water storage over time, capillary rise, groundwater
  contribution, paddy ponding or crop stress functions.
- It does not claim verified water savings; that needs a measured baseline.
"""

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from backend.crop_data import get_crop, get_kc

# --- Fixed conversion --------------------------------------------------------
MM_PER_HA_TO_LITRES = 10_000.0  # 1 mm depth over 1 ha = 10,000 litres

# --- Irrigation efficiency by method (application efficiency, indicative) ----
# Indicative application efficiencies. Drip is high, surface flood is low.
IRRIGATION_EFFICIENCY: Dict[str, float] = {
    "drip": 0.90,
    "sprinkler": 0.75,
    "furrow": 0.60,
    "flood": 0.50,
}

IRRIGATION_METHOD_LABELS: Dict[str, str] = {
    "drip": "Drip",
    "sprinkler": "Sprinkler",
    "furrow": "Furrow",
    "flood": "Flood / Basin",
}

# Below this daily net depth (mm) the requirement is treated as negligible.
NEGLIGIBLE_IRRIGATION_MM = 0.5

# Soil types are recorded and used for advisory notes only. They do NOT change
# the numeric daily water balance in this simplified model.
SOIL_TYPES = ["sandy", "loamy", "clay", "silt", "black", "red", "alluvial"]

SOIL_NOTES: Dict[str, str] = {
    "sandy": "Sandy soils hold little water; expect more frequent, lighter applications.",
    "loamy": "Loamy soils are well balanced; a common, forgiving default.",
    "clay": "Clay soils hold water well but drain slowly; avoid over-application.",
    "silt": "Silty soils hold water well but can crust; watch infiltration.",
    "black": "Black (regur) soils retain moisture strongly; re-check before irrigating.",
    "red": "Red soils are often well drained; check moisture at depth.",
    "alluvial": "Alluvial soils are generally fertile and moisture-retentive.",
}

RECOMMENDATION_IRRIGATE = "Irrigate Now"
RECOMMENDATION_WAIT = "Wait and Reassess"
RECOMMENDATION_INSPECT = "Inspect Field / More Data Needed"


@dataclass
class FieldInput:
    """Validated field parameters for one analysis."""

    crop_id: str
    growth_stage: str
    soil_type: str
    area_ha: float
    irrigation_method: str
    available_water_l: Optional[float] = None
    field_name: str = "Unnamed field"


@dataclass
class WeatherInput:
    """The weather figures the engine consumes for the planning day."""

    et0_mm: Optional[float]
    rainfall_mm: Optional[float]
    source: str = "unknown"
    label: str = ""
    planning_date: Optional[str] = None
    is_demo: bool = False
    extra: Dict[str, Any] = dc_field(default_factory=dict)


def mm_to_litres(depth_mm: float, area_ha: float) -> float:
    """Convert a water depth over an area to litres. 1 mm over 1 ha = 10,000 L."""
    return depth_mm * area_ha * MM_PER_HA_TO_LITRES


def litres_to_mm(litres: float, area_ha: float) -> float:
    """Inverse of mm_to_litres. Returns 0 when area is not positive."""
    if area_ha <= 0:
        return 0.0
    return litres / (area_ha * MM_PER_HA_TO_LITRES)


def _round(value: Optional[float], ndigits: int = 2) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def calculate(field: FieldInput, weather: WeatherInput) -> Dict[str, Any]:
    """
    Run the full irrigation calculation. Pure and deterministic.

    Returns a structured dict with the recommendation, the numbers behind it,
    the reasons, any warnings, and the stated assumptions.
    """
    reasons: List[str] = []
    warnings: List[str] = []
    assumptions: List[str] = [
        "ETc = ET0 x Kc (FAO single crop coefficient method).",
        "Effective rainfall Pe = min(forecast rain, ETc) for the planning day; "
        "rainfall above daily demand is assumed lost to runoff or deep percolation.",
        "Net requirement NIR = max(0, ETc - Pe).",
        "Gross applied water GIR = NIR / irrigation efficiency.",
        "Volume conversion: 1 mm over 1 hectare = 10,000 litres.",
        "Soil type is recorded and advised on, but does not change the numeric "
        "daily water balance in this simplified model.",
        "Weather forecasts are demand-side estimates, not soil-moisture readings.",
    ]

    breakdown: Dict[str, Any] = {}

    # ---- Crop coefficient ---------------------------------------------------
    crop = get_crop(field.crop_id)
    kc, kc_error = get_kc(field.crop_id, field.growth_stage)

    # ---- Efficiency ---------------------------------------------------------
    method = str(field.irrigation_method or "").strip().lower()
    efficiency = IRRIGATION_EFFICIENCY.get(method)

    # ---- Critical-input gate ------------------------------------------------
    missing: List[str] = []
    if field.area_ha is None or field.area_ha <= 0:
        missing.append("a positive field area (hectares)")
    if crop is None:
        missing.append(f"a recognised crop (got '{field.crop_id}')")
    if kc is None and crop is not None:
        missing.append(f"a recognised growth stage (got '{field.growth_stage}')")
    if efficiency is None:
        missing.append(f"a recognised irrigation method (got '{field.irrigation_method}')")
    if weather.et0_mm is None:
        missing.append("a reference evapotranspiration (ET0) value")
    if weather.rainfall_mm is None:
        # Rainfall is optional; absence is treated as 0 with a note, not a gate.
        warnings.append(
            "Forecast rainfall was unavailable; it has been treated as 0 mm for "
            "the planning day."
        )

    if missing:
        reasons.append("Some required inputs are missing or invalid: " + "; ".join(missing) + ".")
        reasons.append("Complete these inputs to get a reliable irrigation recommendation.")
        return {
            "status": "ok",
            "recommendation": RECOMMENDATION_INSPECT,
            "recommendation_code": "inspect",
            "headline": "More data needed before advising on irrigation.",
            "crop": _crop_summary(crop, field),
            "metrics": _empty_metrics(field),
            "breakdown": breakdown,
            "reasons": reasons,
            "warnings": warnings,
            "assumptions": assumptions,
            "inputs_echo": _echo(field, weather),
        }

    # ---- Core calculation ---------------------------------------------------
    et0 = float(weather.et0_mm)
    rainfall = float(weather.rainfall_mm) if weather.rainfall_mm is not None else 0.0
    if rainfall < 0:
        warnings.append("Negative rainfall received; treated as 0 mm.")
        rainfall = 0.0
    area_ha = float(field.area_ha)

    etc_mm = et0 * kc                          # crop water demand
    effective_rainfall_mm = min(rainfall, etc_mm)
    net_irrigation_mm = max(0.0, etc_mm - effective_rainfall_mm)
    gross_irrigation_mm = net_irrigation_mm / efficiency

    net_volume_l = mm_to_litres(net_irrigation_mm, area_ha)
    gross_volume_l = mm_to_litres(gross_irrigation_mm, area_ha)
    etc_volume_l = mm_to_litres(etc_mm, area_ha)

    # ---- Available-water check ---------------------------------------------
    available_water_l = field.available_water_l
    sufficiency = "unknown"
    deficit_l = None
    if available_water_l is not None and available_water_l >= 0:
        deficit_l = max(0.0, gross_volume_l - available_water_l)
        sufficiency = "sufficient" if available_water_l >= gross_volume_l else "insufficient"

    breakdown = {
        "et0_mm": _round(et0),
        "kc": _round(kc),
        "crop_water_demand_mm": _round(etc_mm),
        "crop_water_demand_volume_l": _round(etc_volume_l, 0),
        "forecast_rainfall_mm": _round(rainfall),
        "effective_rainfall_mm": _round(effective_rainfall_mm),
        "net_irrigation_mm": _round(net_irrigation_mm),
        "irrigation_efficiency": _round(efficiency),
        "gross_irrigation_mm": _round(gross_irrigation_mm),
        "area_ha": _round(area_ha),
        "net_volume_l": _round(net_volume_l, 0),
        "gross_volume_l": _round(gross_volume_l, 0),
        "available_water_l": _round(available_water_l, 0),
        "deficit_l": _round(deficit_l, 0),
        "conversion": "1 mm over 1 ha = 10,000 litres",
    }

    # ---- Decision logic -----------------------------------------------------
    recommendation, code, headline = _decide(
        net_irrigation_mm, rainfall, sufficiency, reasons, warnings
    )

    # ---- Supporting notes ---------------------------------------------------
    if effective_rainfall_mm > 0:
        reasons.append(
            f"Forecast rainfall ({rainfall:.2f} mm) is credited up to the day's "
            f"demand, giving {effective_rainfall_mm:.2f} mm of effective rainfall."
        )
    if rainfall > etc_mm and etc_mm > 0:
        reasons.append(
            "Forecast rainfall exceeds the crop's daily demand; the excess is not "
            "credited (assumed lost to runoff or deep percolation)."
        )

    soil = str(field.soil_type or "").strip().lower()
    if soil in SOIL_NOTES:
        assumptions.append(f"Soil note: {SOIL_NOTES[soil]}")

    if sufficiency == "insufficient":
        warnings.append(
            f"Available water ({available_water_l:,.0f} L) is below the gross "
            f"requirement ({gross_volume_l:,.0f} L). A shortfall of "
            f"{deficit_l:,.0f} L cannot be met from the stated supply."
        )
    elif sufficiency == "sufficient":
        reasons.append(
            f"Available water ({available_water_l:,.0f} L) covers the gross "
            f"requirement ({gross_volume_l:,.0f} L)."
        )

    return {
        "status": "ok",
        "recommendation": recommendation,
        "recommendation_code": code,
        "headline": headline,
        "crop": _crop_summary(crop, field),
        "metrics": {
            "net_irrigation_mm": _round(net_irrigation_mm),
            "net_volume_l": _round(net_volume_l, 0),
            "gross_irrigation_mm": _round(gross_irrigation_mm),
            "gross_volume_l": _round(gross_volume_l, 0),
            "crop_water_demand_mm": _round(etc_mm),
            "crop_water_demand_volume_l": _round(etc_volume_l, 0),
            "effective_rainfall_mm": _round(effective_rainfall_mm),
            "forecast_rainfall_mm": _round(rainfall),
            "available_water_l": _round(available_water_l, 0),
            "water_status": sufficiency,
            "deficit_l": _round(deficit_l, 0),
        },
        "breakdown": breakdown,
        "reasons": reasons,
        "warnings": warnings,
        "assumptions": assumptions,
        "inputs_echo": _echo(field, weather),
    }


def _decide(net_mm, rainfall_mm, sufficiency, reasons, warnings):
    """Map the computed requirement to one of the three recommendation states."""
    if net_mm < NEGLIGIBLE_IRRIGATION_MM:
        reasons.append(
            f"Net irrigation requirement is {net_mm:.2f} mm, below the "
            f"{NEGLIGIBLE_IRRIGATION_MM} mm threshold."
        )
        if rainfall_mm > 0:
            reasons.append("Forecast rainfall is expected to meet the crop's demand.")
        else:
            reasons.append(
                "Crop demand is very low for this stage; re-check tomorrow."
            )
        return RECOMMENDATION_WAIT, "wait", "No irrigation needed today. Reassess tomorrow."

    if sufficiency == "insufficient":
        reasons.append(
            "Crop demand exceeds what current rainfall will supply, but available "
            "water is not enough to meet the full requirement."
        )
        reasons.append(
            "Inspect the field and water source, then reassess with a realistic "
            "available-water figure."
        )
        return (
            RECOMMENDATION_INSPECT,
            "inspect",
            "Insufficient water to meet the full requirement.",
        )

    reasons.append(
        f"Crop demand exceeds effective rainfall by {net_mm:.2f} mm, so irrigation "
        f"is recommended."
    )
    return RECOMMENDATION_IRRIGATE, "irrigate", "Irrigation recommended today."


def _crop_summary(crop, field):
    if crop is None:
        return {"id": field.crop_id, "name": field.crop_id, "kc": None}
    return {
        "id": crop["id"],
        "name": crop["name"],
        "local_name": crop.get("local_name"),
        "category": crop.get("category"),
        "growth_stage": field.growth_stage,
        "kc": crop["kc"].get(str(field.growth_stage or "").strip().lower()),
        "source": crop.get("source"),
    }


def _empty_metrics(field):
    return {
        "net_irrigation_mm": None,
        "net_volume_l": None,
        "gross_irrigation_mm": None,
        "gross_volume_l": None,
        "crop_water_demand_mm": None,
        "crop_water_demand_volume_l": None,
        "effective_rainfall_mm": None,
        "forecast_rainfall_mm": None,
        "available_water_l": _round(field.available_water_l, 0),
        "water_status": "unknown",
        "deficit_l": None,
    }


def _echo(field, weather):
    return {
        "field_name": field.field_name,
        "crop_id": field.crop_id,
        "growth_stage": field.growth_stage,
        "soil_type": field.soil_type,
        "area_ha": _round(field.area_ha),
        "irrigation_method": field.irrigation_method,
        "available_water_l": _round(field.available_water_l, 0),
        "weather_source": weather.source,
        "weather_label": weather.label,
        "weather_is_demo": weather.is_demo,
        "planning_date": weather.planning_date,
    }
