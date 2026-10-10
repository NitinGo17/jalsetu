"""
crop_data.py
------------
Reference crop data for JalSetu: crop coefficients (Kc) by growth stage,
plus descriptive metadata.

SOURCE BASIS
------------
The Kc values are *indicative reference values* derived from the FAO single
crop coefficient method described in FAO Irrigation and Drainage Paper 56
(Allen, Pereira, Raes & Smith, 1998), Table 12. They are tabulated averages
for well-managed, disease-free crops under non-stressed conditions.

JALSETU SIMPLIFICATION (stated explicitly, not hidden)
------------------------------------------------------
FAO-56 defines four growth stages: initial, crop development, mid-season and
late season. JalSetu presents farmer-friendly stage names and maps them:

    initial     -> FAO "initial"      -> Kc_ini
    vegetative  -> FAO "development"  -> Kc_ini + 0.6 * (Kc_mid - Kc_ini)
    flowering   -> FAO "mid-season"   -> Kc_mid
    maturity    -> FAO "late season"  -> Kc_end

The "vegetative" value is a JalSetu interpolation (60% of the way from the
initial to the mid-season coefficient). It is NOT a published FAO number and
is labelled as a simplification wherever it is shown to the user.

These values are reference guidance, not field-calibrated coefficients.
Local soil, cultivar, climate and management will shift the true value.
"""

from typing import Any, Dict

# Growth stages JalSetu exposes, in order.
GROWTH_STAGES = ["initial", "vegetative", "flowering", "maturity"]

GROWTH_STAGE_LABELS = {
    "initial": "Initial / Establishment",
    "vegetative": "Vegetative",
    "flowering": "Flowering / Reproductive",
    "maturity": "Maturity / Ripening",
}


def _stage_kc(kc_ini: float, kc_mid: float, kc_end: float) -> Dict[str, float]:
    """Expand FAO-56 initial/mid/end Kc into JalSetu's four stages."""
    return {
        "initial": round(kc_ini, 2),
        "vegetative": round(kc_ini + 0.6 * (kc_mid - kc_ini), 2),
        "flowering": round(kc_mid, 2),
        "maturity": round(kc_end, 2),
    }


# Each entry: id, display name, a local-language label, category, Kc by stage,
# indicative rooting depth, a short note, and the stated source.
CROPS: Dict[str, Dict[str, Any]] = {
    "wheat": {
        "id": "wheat",
        "name": "Wheat",
        "local_name": "Gehun (गेहूं)",
        "category": "Cereal",
        "kc": _stage_kc(0.40, 1.15, 0.40),
        "root_depth_m": 1.2,
        "notes": "Rabi (winter) cereal. Peak demand during flowering and grain fill.",
        "source": "FAO-56 Table 12 (winter wheat, indicative)",
    },
    "rice": {
        "id": "rice",
        "name": "Rice (Paddy)",
        "local_name": "Dhan (धान)",
        "category": "Cereal",
        "kc": _stage_kc(1.05, 1.20, 0.90),
        "root_depth_m": 0.5,
        "notes": "Kharif cereal, normally grown flooded. Values assume a ponded "
        "system; JalSetu's daily balance does not model paddy ponding.",
        "source": "FAO-56 Table 12 (paddy rice, indicative)",
    },
    "maize": {
        "id": "maize",
        "name": "Maize",
        "local_name": "Makka (मक्का)",
        "category": "Cereal",
        "kc": _stage_kc(0.30, 1.20, 0.35),
        "root_depth_m": 1.0,
        "notes": "Grain maize. Highly sensitive to water stress at tasselling and silking.",
        "source": "FAO-56 Table 12 (field/grain maize, indicative)",
    },
    "sorghum": {
        "id": "sorghum",
        "name": "Sorghum",
        "local_name": "Jowar (ज्वार)",
        "category": "Cereal",
        "kc": _stage_kc(0.35, 1.10, 0.55),
        "root_depth_m": 1.2,
        "notes": "Drought-tolerant cereal; useful in low-rainfall rotations.",
        "source": "FAO-56 Table 12 (sorghum, indicative)",
    },
    "pearl_millet": {
        "id": "pearl_millet",
        "name": "Pearl Millet",
        "local_name": "Bajra (बाजरा)",
        "category": "Cereal",
        "kc": _stage_kc(0.30, 1.00, 0.55),
        "root_depth_m": 1.2,
        "notes": "Hardy kharif millet suited to dryland conditions.",
        "source": "FAO-56 Table 12 (millet, indicative)",
    },
    "chickpea": {
        "id": "chickpea",
        "name": "Chickpea",
        "local_name": "Chana (चना)",
        "category": "Pulse",
        "kc": _stage_kc(0.40, 1.05, 0.35),
        "root_depth_m": 0.9,
        "notes": "Rabi pulse; generally lower water demand than cereals.",
        "source": "FAO-56 Table 12 (chickpea, indicative)",
    },
    "lentil": {
        "id": "lentil",
        "name": "Lentil",
        "local_name": "Masoor (मसूर)",
        "category": "Pulse",
        "kc": _stage_kc(0.40, 1.10, 0.30),
        "root_depth_m": 0.8,
        "notes": "Rabi pulse; sensitive to waterlogging.",
        "source": "FAO-56 Table 12 (lentil, indicative)",
    },
    "groundnut": {
        "id": "groundnut",
        "name": "Groundnut",
        "local_name": "Moongphali (मूंगफली)",
        "category": "Oilseed",
        "kc": _stage_kc(0.40, 1.15, 0.60),
        "root_depth_m": 0.7,
        "notes": "Kharif oilseed. Peak demand during pegging and pod fill.",
        "source": "FAO-56 Table 12 (groundnut, indicative)",
    },
    "soybean": {
        "id": "soybean",
        "name": "Soybean",
        "local_name": "Soyabean (सोयाबीन)",
        "category": "Oilseed",
        "kc": _stage_kc(0.40, 1.15, 0.50),
        "root_depth_m": 0.8,
        "notes": "Kharif oilseed; critical stage at flowering and pod fill.",
        "source": "FAO-56 Table 12 (soybean, indicative)",
    },
    "mustard": {
        "id": "mustard",
        "name": "Mustard / Rapeseed",
        "local_name": "Sarson (सरसों)",
        "category": "Oilseed",
        "kc": _stage_kc(0.35, 1.10, 0.35),
        "root_depth_m": 1.0,
        "notes": "Rabi oilseed; moderate demand, sensitive at flowering.",
        "source": "FAO-56 Table 12 (rapeseed/mustard, indicative)",
    },
    "cotton": {
        "id": "cotton",
        "name": "Cotton",
        "local_name": "Kapas (कपास)",
        "category": "Fibre",
        "kc": _stage_kc(0.35, 1.18, 0.60),
        "root_depth_m": 1.1,
        "notes": "Long-duration kharif fibre crop; peak demand at boll formation.",
        "source": "FAO-56 Table 12 (cotton, indicative)",
    },
    "sugarcane": {
        "id": "sugarcane",
        "name": "Sugarcane",
        "local_name": "Ganna (गन्ना)",
        "category": "Cash",
        "kc": _stage_kc(0.40, 1.25, 0.75),
        "root_depth_m": 1.3,
        "notes": "Year-round cash crop with sustained high water demand.",
        "source": "FAO-56 Table 12 (sugarcane, indicative)",
    },
    "tomato": {
        "id": "tomato",
        "name": "Tomato",
        "local_name": "Tamatar (टमाटर)",
        "category": "Vegetable",
        "kc": _stage_kc(0.60, 1.15, 0.80),
        "root_depth_m": 0.7,
        "notes": "Vegetable; benefits strongly from drip and mulching.",
        "source": "FAO-56 Table 12 (tomato, indicative)",
    },
    "potato": {
        "id": "potato",
        "name": "Potato",
        "local_name": "Aloo (आलू)",
        "category": "Vegetable",
        "kc": _stage_kc(0.50, 1.15, 0.75),
        "root_depth_m": 0.5,
        "notes": "Rabi vegetable; shallow roots, sensitive to moisture swings.",
        "source": "FAO-56 Table 12 (potato, indicative)",
    },
    "onion": {
        "id": "onion",
        "name": "Onion",
        "local_name": "Pyaz (प्याज)",
        "category": "Vegetable",
        "kc": _stage_kc(0.70, 1.05, 0.75),
        "root_depth_m": 0.4,
        "notes": "Shallow-rooted; frequent light irrigation is typical.",
        "source": "FAO-56 Table 12 (onion, indicative)",
    },
    "chilli": {
        "id": "chilli",
        "name": "Chilli",
        "local_name": "Mirchi (मिर्च)",
        "category": "Vegetable",
        "kc": _stage_kc(0.60, 1.05, 0.90),
        "root_depth_m": 0.6,
        "notes": "Long-duration vegetable; steady demand across flowering and fruiting.",
        "source": "FAO-56 Table 12 (pepper/chilli, indicative)",
    },
}


def list_crops():
    """Return crop metadata as a list, ordered for stable display."""
    return list(CROPS.values())


def get_crop(crop_id: str):
    """Return a crop dict by id, or None if unknown."""
    if not crop_id:
        return None
    return CROPS.get(str(crop_id).strip().lower())


def get_kc(crop_id: str, growth_stage: str):
    """
    Return (kc, error). kc is a float when resolvable, else None with a
    human-readable error explaining exactly what is missing.
    """
    crop = get_crop(crop_id)
    if crop is None:
        return None, f"Unknown crop '{crop_id}'."
    stage = str(growth_stage or "").strip().lower()
    if stage not in GROWTH_STAGES:
        return None, (
            f"Unknown growth stage '{growth_stage}'. "
            f"Expected one of: {', '.join(GROWTH_STAGES)}."
        )
    return crop["kc"][stage], None
