"""
weather.py
----------
Weather access for JalSetu.

Primary source: Open-Meteo (https://open-meteo.com), a free, key-less weather
API. We use the forecast endpoint for daily reference evapotranspiration
(et0_fao_evapotranspiration), precipitation and temperature, and the geocoding
endpoint to turn a place name into coordinates.

Everything the API can fail at is handled here: timeouts, HTTP errors, missing
variables, malformed payloads and unknown locations. When live data cannot be
obtained, the caller can fall back to an explicitly labelled DEMO forecast.
Simulated values are never presented as live data.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "et0_fao_evapotranspiration",
]
CURRENT_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "weather_code",
    "precipitation",
]

REQUEST_TIMEOUT = 12.0  # seconds

# WMO weather interpretation codes -> short text (Open-Meteo convention).
WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def weather_text(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return WMO_CODES.get(int(code), "Unknown")


class WeatherError(Exception):
    """Raised when live weather cannot be retrieved or parsed."""


# ---------------------------------------------------------------------------
# Built-in coordinate fallback
# ---------------------------------------------------------------------------
# Used ONLY when the Open-Meteo geocoding service cannot be reached, so that
# live weather still works for well-known Indian places on a restricted
# network. Coordinates are approximate district/city centres and are labelled
# as a built-in fallback wherever they are used.
_INDIA_PLACES: Dict[str, Dict[str, Any]] = {
    "prayagraj": {"name": "Prayagraj", "state": "Uttar Pradesh", "latitude": 25.4358, "longitude": 81.8463},
    "allahabad": {"name": "Prayagraj", "state": "Uttar Pradesh", "latitude": 25.4358, "longitude": 81.8463},
    "lucknow": {"name": "Lucknow", "state": "Uttar Pradesh", "latitude": 26.8467, "longitude": 80.9462},
    "kanpur": {"name": "Kanpur", "state": "Uttar Pradesh", "latitude": 26.4499, "longitude": 80.3319},
    "varanasi": {"name": "Varanasi", "state": "Uttar Pradesh", "latitude": 25.3176, "longitude": 82.9739},
    "agra": {"name": "Agra", "state": "Uttar Pradesh", "latitude": 27.1767, "longitude": 78.0081},
    "meerut": {"name": "Meerut", "state": "Uttar Pradesh", "latitude": 28.9845, "longitude": 77.7064},
    "nashik": {"name": "Nashik", "state": "Maharashtra", "latitude": 19.9975, "longitude": 73.7898},
    "mumbai": {"name": "Mumbai", "state": "Maharashtra", "latitude": 19.0760, "longitude": 72.8777},
    "pune": {"name": "Pune", "state": "Maharashtra", "latitude": 18.5204, "longitude": 73.8567},
    "nagpur": {"name": "Nagpur", "state": "Maharashtra", "latitude": 21.1458, "longitude": 79.0882},
    "aurangabad": {"name": "Aurangabad", "state": "Maharashtra", "latitude": 19.8762, "longitude": 75.3433},
    "solapur": {"name": "Solapur", "state": "Maharashtra", "latitude": 17.6599, "longitude": 75.9064},
    "jodhpur": {"name": "Jodhpur", "state": "Rajasthan", "latitude": 26.2389, "longitude": 73.0243},
    "jaipur": {"name": "Jaipur", "state": "Rajasthan", "latitude": 26.9124, "longitude": 75.7873},
    "kota": {"name": "Kota", "state": "Rajasthan", "latitude": 25.2138, "longitude": 75.8648},
    "udaipur": {"name": "Udaipur", "state": "Rajasthan", "latitude": 24.5854, "longitude": 73.7125},
    "bikaner": {"name": "Bikaner", "state": "Rajasthan", "latitude": 28.0229, "longitude": 73.3119},
    "delhi": {"name": "Delhi", "state": "Delhi", "latitude": 28.6139, "longitude": 77.2090},
    "new delhi": {"name": "New Delhi", "state": "Delhi", "latitude": 28.6139, "longitude": 77.2090},
    "ludhiana": {"name": "Ludhiana", "state": "Punjab", "latitude": 30.9010, "longitude": 75.8573},
    "amritsar": {"name": "Amritsar", "state": "Punjab", "latitude": 31.6340, "longitude": 74.8723},
    "jalandhar": {"name": "Jalandhar", "state": "Punjab", "latitude": 31.3260, "longitude": 75.5762},
    "hisar": {"name": "Hisar", "state": "Haryana", "latitude": 29.1492, "longitude": 75.7217},
    "karnal": {"name": "Karnal", "state": "Haryana", "latitude": 29.6857, "longitude": 76.9905},
    "bhopal": {"name": "Bhopal", "state": "Madhya Pradesh", "latitude": 23.2599, "longitude": 77.4126},
    "indore": {"name": "Indore", "state": "Madhya Pradesh", "latitude": 22.7196, "longitude": 75.8577},
    "gwalior": {"name": "Gwalior", "state": "Madhya Pradesh", "latitude": 26.2183, "longitude": 78.1828},
    "jabalpur": {"name": "Jabalpur", "state": "Madhya Pradesh", "latitude": 23.1815, "longitude": 79.9864},
    "ahmedabad": {"name": "Ahmedabad", "state": "Gujarat", "latitude": 23.0225, "longitude": 72.5714},
    "surat": {"name": "Surat", "state": "Gujarat", "latitude": 21.1702, "longitude": 72.8311},
    "rajkot": {"name": "Rajkot", "state": "Gujarat", "latitude": 22.3039, "longitude": 70.8022},
    "patna": {"name": "Patna", "state": "Bihar", "latitude": 25.5941, "longitude": 85.1376},
    "hyderabad": {"name": "Hyderabad", "state": "Telangana", "latitude": 17.3850, "longitude": 78.4867},
    "warangal": {"name": "Warangal", "state": "Telangana", "latitude": 17.9689, "longitude": 79.5941},
    "vijayawada": {"name": "Vijayawada", "state": "Andhra Pradesh", "latitude": 16.5062, "longitude": 80.6480},
    "visakhapatnam": {"name": "Visakhapatnam", "state": "Andhra Pradesh", "latitude": 17.6868, "longitude": 83.2185},
    "kurnool": {"name": "Kurnool", "state": "Andhra Pradesh", "latitude": 15.8281, "longitude": 78.0373},
    "bengaluru": {"name": "Bengaluru", "state": "Karnataka", "latitude": 12.9716, "longitude": 77.5946},
    "bangalore": {"name": "Bengaluru", "state": "Karnataka", "latitude": 12.9716, "longitude": 77.5946},
    "mysuru": {"name": "Mysuru", "state": "Karnataka", "latitude": 12.2958, "longitude": 76.6394},
    "hubballi": {"name": "Hubballi", "state": "Karnataka", "latitude": 15.3647, "longitude": 75.1240},
    "belagavi": {"name": "Belagavi", "state": "Karnataka", "latitude": 15.8497, "longitude": 74.4977},
    "chennai": {"name": "Chennai", "state": "Tamil Nadu", "latitude": 13.0827, "longitude": 80.2707},
    "coimbatore": {"name": "Coimbatore", "state": "Tamil Nadu", "latitude": 11.0168, "longitude": 76.9558},
    "madurai": {"name": "Madurai", "state": "Tamil Nadu", "latitude": 9.9252, "longitude": 78.1198},
    "tiruchirappalli": {"name": "Tiruchirappalli", "state": "Tamil Nadu", "latitude": 10.7905, "longitude": 78.7047},
    "kolkata": {"name": "Kolkata", "state": "West Bengal", "latitude": 22.5726, "longitude": 88.3639},
    "bhubaneswar": {"name": "Bhubaneswar", "state": "Odisha", "latitude": 20.2961, "longitude": 85.8245},
    "raipur": {"name": "Raipur", "state": "Chhattisgarh", "latitude": 21.2514, "longitude": 81.6296},
    "ranchi": {"name": "Ranchi", "state": "Jharkhand", "latitude": 23.3441, "longitude": 85.3096},
    "guwahati": {"name": "Guwahati", "state": "Assam", "latitude": 26.1445, "longitude": 91.7362},
    "dehradun": {"name": "Dehradun", "state": "Uttarakhand", "latitude": 30.3165, "longitude": 78.0322},
    "chandigarh": {"name": "Chandigarh", "state": "Chandigarh", "latitude": 30.7333, "longitude": 76.7794},
    "kochi": {"name": "Kochi", "state": "Kerala", "latitude": 9.9312, "longitude": 76.2673},
    "thrissur": {"name": "Thrissur", "state": "Kerala", "latitude": 10.5276, "longitude": 76.2144},
}


def _normalise_place(name: str) -> str:
    return " ".join(str(name or "").lower().replace(",", " ").split())


def lookup_place(name: str) -> Optional[Dict[str, Any]]:
    """Look up built-in coordinates. Tries the full string, then each token."""
    key = _normalise_place(name)
    if key in _INDIA_PLACES:
        return _INDIA_PLACES[key]
    for token in key.split():
        if token in _INDIA_PLACES:
            return _INDIA_PLACES[token]
    return None


# ---------------------------------------------------------------------------
# Live access
# ---------------------------------------------------------------------------
async def geocode_location(name: str) -> Dict[str, Any]:
    """Resolve a place name to coordinates via Open-Meteo geocoding."""
    query = str(name or "").strip()
    if not query:
        raise WeatherError("No location name provided.")

    params = {"name": query, "count": 1, "language": "en", "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(GEOCODE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException as exc:
        raise WeatherError("Location lookup timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise WeatherError(f"Location lookup failed (HTTP {exc.response.status_code}).") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherError(f"Location lookup failed: {exc}") from exc

    results = data.get("results") or []
    if not results:
        raise WeatherError(f"Could not find a location named '{query}'.")
    top = results[0]
    return {
        "name": top.get("name"),
        "admin1": top.get("admin1"),
        "country": top.get("country"),
        "latitude": top.get("latitude"),
        "longitude": top.get("longitude"),
        "timezone": top.get("timezone"),
    }


async def fetch_forecast(latitude: float, longitude: float,
                         location: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fetch and normalise an Open-Meteo forecast. Raises WeatherError on failure."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(DAILY_VARS),
        "current": ",".join(CURRENT_VARS),
        "timezone": "auto",
        "forecast_days": 7,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(FORECAST_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException as exc:
        raise WeatherError("Weather request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise WeatherError(f"Weather request failed (HTTP {exc.response.status_code}).") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherError(f"Weather request failed: {exc}") from exc

    return _normalise(data, source="live", is_demo=False, location=location)


def _normalise(data: Dict[str, Any], source: str, is_demo: bool,
               location: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    daily = data.get("daily") or {}
    current = data.get("current") or {}
    times: List[str] = daily.get("time") or []
    if not times:
        raise WeatherError("Weather response contained no daily data.")

    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_sum") or []
    et0 = daily.get("et0_fao_evapotranspiration") or []

    missing_vars = []
    if not et0:
        missing_vars.append("et0_fao_evapotranspiration")
    if not precip:
        missing_vars.append("precipitation_sum")

    # Planning day: prefer tomorrow (index 1) when available, else today.
    idx = 1 if len(times) > 1 else 0

    def at(seq, i):
        return seq[i] if i < len(seq) else None

    planning = {
        "index": idx,
        "date": at(times, idx),
        "et0_mm": at(et0, idx),
        "rainfall_mm": at(precip, idx),
        "tmax": at(tmax, idx),
        "tmin": at(tmin, idx),
    }

    forecast = []
    for i, d in enumerate(times):
        forecast.append({
            "date": d,
            "tmax": at(tmax, i),
            "tmin": at(tmin, i),
            "rainfall_mm": at(precip, i),
            "et0_mm": at(et0, i),
        })

    rainfall_total = round(sum(v for v in precip if isinstance(v, (int, float))), 1) if precip else None
    rainfall_next72 = None
    if precip:
        window = [v for v in precip[:3] if isinstance(v, (int, float))]
        rainfall_next72 = round(sum(window), 1) if window else None

    code = current.get("weather_code")
    result = {
        "source": source,                       # "live" or "demo"
        "provider": "Open-Meteo" if source == "live" else "JalSetu demo dataset",
        "is_demo": is_demo,
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "timezone": data.get("timezone"),
        "timezone_abbreviation": data.get("timezone_abbreviation"),
        "elevation": data.get("elevation"),
        "location": location or {
            "name": None,
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        },
        "current": {
            "time": current.get("time"),
            "temperature_2m": current.get("temperature_2m"),
            "relative_humidity_2m": current.get("relative_humidity_2m"),
            "wind_speed_10m": current.get("wind_speed_10m"),
            "weather_code": code,
            "weather_text": weather_text(code),
            "precipitation": current.get("precipitation"),
        },
        "daily": {
            "time": times,
            "temperature_2m_max": tmax,
            "temperature_2m_min": tmin,
            "precipitation_sum": precip,
            "et0_fao_evapotranspiration": et0,
        },
        "forecast": forecast,
        "planning_day": planning,
        "rainfall_summary": {
            "seven_day_total_mm": rainfall_total,
            "next_72h_total_mm": rainfall_next72,
        },
        "missing_variables": missing_vars,
        "error": None,
        "message": (
            "Live data from Open-Meteo."
            if source == "live"
            else "DEMO data — a fixed sample forecast, not live weather."
        ),
    }
    return result


# ---------------------------------------------------------------------------
# Demo scenarios (deterministic; independent of live weather)
# ---------------------------------------------------------------------------
# Each scenario is a complete, reproducible situation a presenter can switch to
# without any network access. Weather values are fixed sample figures.
DEMO_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "dry",
        "name": "Dry spell — irrigation needed",
        "description": "Hot, dry days with no forecast rain. Wheat at flowering. "
                       "Ample water available. Expect 'Irrigate Now'.",
        "field": {
            "field_name": "Demo: Dry Spell Field",
            "location": "Prayagraj, Uttar Pradesh",
            "latitude": 25.4358,
            "longitude": 81.8463,
            "crop_id": "wheat",
            "growth_stage": "flowering",
            "soil_type": "loamy",
            "area_ha": 1.0,
            "irrigation_method": "drip",
            "available_water_l": 100000,
        },
        "weather": {
            "et0_mm": 6.2,
            "rainfall_mm": 0.0,
            "tmax": 36.0,
            "tmin": 22.0,
            "series_rainfall": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "series_tmax": [35.0, 36.0, 37.0, 36.5, 35.5, 34.0, 33.0],
            "series_tmin": [22.0, 22.0, 23.0, 23.5, 23.0, 22.5, 22.0],
            "series_et0": [5.8, 6.2, 6.4, 6.1, 5.9, 5.6, 5.4],
        },
    },
    {
        "id": "rain",
        "name": "Forecast rainfall — wait",
        "description": "Meaningful rain forecast, enough to meet the crop's daily "
                       "demand. Expect 'Wait and Reassess'.",
        "field": {
            "field_name": "Demo: Rain Incoming Field",
            "location": "Nashik, Maharashtra",
            "latitude": 19.9975,
            "longitude": 73.7898,
            "crop_id": "maize",
            "growth_stage": "vegetative",
            "soil_type": "black",
            "area_ha": 0.8,
            "irrigation_method": "sprinkler",
            "available_water_l": 40000,
        },
        "weather": {
            "et0_mm": 4.6,
            "rainfall_mm": 18.0,
            "tmax": 29.0,
            "tmin": 22.0,
            "series_rainfall": [0.0, 18.0, 12.0, 4.0, 0.0, 0.0, 0.0],
            "series_tmax": [30.0, 29.0, 28.0, 30.0, 31.0, 32.0, 32.0],
            "series_tmin": [23.0, 22.0, 21.5, 22.0, 22.5, 23.0, 23.0],
            "series_et0": [4.8, 4.6, 3.9, 4.4, 4.9, 5.1, 5.2],
        },
    },
    {
        "id": "scarcity",
        "name": "Water scarcity — insufficient supply",
        "description": "Hot, dry conditions and a small water reserve that cannot "
                       "meet the requirement. Expect 'Inspect Field / More Data Needed'.",
        "field": {
            "field_name": "Demo: Scarce Water Field",
            "location": "Jodhpur, Rajasthan",
            "latitude": 26.2389,
            "longitude": 73.0243,
            "crop_id": "cotton",
            "growth_stage": "flowering",
            "soil_type": "sandy",
            "area_ha": 2.0,
            "irrigation_method": "flood",
            "available_water_l": 30000,
        },
        "weather": {
            "et0_mm": 6.8,
            "rainfall_mm": 0.0,
            "tmax": 38.0,
            "tmin": 25.0,
            "series_rainfall": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "series_tmax": [37.0, 38.0, 39.0, 38.0, 37.0, 36.0, 36.0],
            "series_tmin": [24.0, 25.0, 26.0, 25.5, 25.0, 24.5, 24.0],
            "series_et0": [6.4, 6.8, 7.0, 6.7, 6.5, 6.2, 6.1],
        },
    },
]


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    for s in DEMO_SCENARIOS:
        if s["id"] == scenario_id:
            return s
    return None


def build_demo_forecast(scenario_id: str, start: Optional[_dt.date] = None) -> Dict[str, Any]:
    """Build a normalised, explicitly-labelled demo forecast for a scenario."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise WeatherError(f"Unknown demo scenario '{scenario_id}'.")

    w = scenario["weather"]
    start = start or _dt.date.today()
    times = [(start + _dt.timedelta(days=i)).isoformat() for i in range(7)]

    data = {
        "timezone": "Asia/Kolkata",
        "timezone_abbreviation": "IST",
        "elevation": None,
        "daily": {
            "time": times,
            "temperature_2m_max": w["series_tmax"],
            "temperature_2m_min": w["series_tmin"],
            "precipitation_sum": w["series_rainfall"],
            "et0_fao_evapotranspiration": w["series_et0"],
        },
        "current": {
            "time": times[0] + "T09:00",
            "temperature_2m": w["tmax"],
            "relative_humidity_2m": 40,
            "wind_speed_10m": 12.0,
            "weather_code": 0 if w["rainfall_mm"] == 0 else 61,
            "precipitation": w["rainfall_mm"],
        },
    }
    loc = {
        "name": scenario["field"]["location"],
        "latitude": scenario["field"]["latitude"],
        "longitude": scenario["field"]["longitude"],
    }
    normalised = _normalise(data, source="demo", is_demo=True, location=loc)
    normalised["scenario"] = {"id": scenario["id"], "name": scenario["name"]}
    # Force the planning day to the scenario's stated values (index 1 = tomorrow).
    normalised["planning_day"]["et0_mm"] = w["et0_mm"]
    normalised["planning_day"]["rainfall_mm"] = w["rainfall_mm"]
    return normalised


async def get_weather(location: Optional[str] = None,
                      latitude: Optional[float] = None,
                      longitude: Optional[float] = None,
                      demo: bool = False,
                      scenario: Optional[str] = None,
                      allow_fallback: bool = True) -> Dict[str, Any]:
    """
    Resolve weather for a location, live when possible.

    If live retrieval fails and allow_fallback is True, returns an explicitly
    labelled demo forecast (default scenario 'dry') so the app stays usable.
    The returned dict always says which it is via source/is_demo/message.
    """
    if demo:
        result = build_demo_forecast(scenario or "dry")
        result["requested"] = {"location": location, "demo": True}
        return result

    # Resolve coordinates.
    loc_meta = None
    lat, lon = latitude, longitude
    resolve_note = None
    if lat is None or lon is None:
        if not location:
            exc = WeatherError("Provide a location name or coordinates.")
            if allow_fallback:
                result = build_demo_forecast(scenario or "dry")
                result["error"] = str(exc)
                result["message"] = (
                    f"Live weather unavailable ({exc}). Showing DEMO data — not live weather."
                )
                return result
            raise exc
        try:
            loc_meta = await geocode_location(location)
            lat = loc_meta.get("latitude")
            lon = loc_meta.get("longitude")
        except WeatherError as exc:
            local = lookup_place(location)
            if local:
                lat, lon = local["latitude"], local["longitude"]
                loc_meta = {
                    "name": local["name"], "admin1": local.get("state"),
                    "country": "India", "latitude": lat, "longitude": lon,
                    "timezone": "Asia/Kolkata",
                }
                resolve_note = (
                    f"Geocoding was unavailable ({exc}); used JalSetu's built-in "
                    f"coordinates for {local['name']}."
                )
            else:
                if allow_fallback:
                    result = build_demo_forecast(scenario or "dry")
                    result["error"] = str(exc)
                    result["message"] = (
                        f"Live weather unavailable ({exc}). Showing DEMO data — not live weather."
                    )
                    return result
                raise

    if lat is None or lon is None:
        exc = WeatherError("Could not resolve coordinates for the location.")
        if allow_fallback:
            result = build_demo_forecast(scenario or "dry")
            result["error"] = str(exc)
            result["message"] = (
                f"Live weather unavailable ({exc}). Showing DEMO data — not live weather."
            )
            return result
        raise exc

    try:
        result = await fetch_forecast(lat, lon, location=loc_meta)
        result["requested"] = {"location": location, "latitude": lat, "longitude": lon}
        if resolve_note:
            result["resolve_note"] = resolve_note
        return result
    except WeatherError as exc:
        if allow_fallback:
            result = build_demo_forecast(scenario or "dry")
            result["error"] = str(exc)
            result["message"] = (
                f"Live weather unavailable ({exc}). Showing DEMO data — not live weather."
            )
            return result
        raise
