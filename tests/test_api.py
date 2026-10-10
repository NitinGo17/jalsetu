"""
API tests. They use the deterministic demo scenarios and an explicit weather
override, so no network access is required.
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_crops_returns_reference_data():
    r = client.get("/api/crops")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 10
    ids = {c["id"] for c in body["crops"]}
    assert {"wheat", "rice", "maize", "cotton"} <= ids


def test_meta_lists_methods_and_states():
    r = client.get("/api/meta")
    body = r.json()
    assert len(body["irrigation_methods"]) == 4
    assert "Irrigate Now" in body["recommendation_states"]


def test_scenarios_returns_three():
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()["scenarios"]}
    assert ids == {"dry", "rain", "scarcity"}


def test_weather_demo_marks_source_as_demo():
    r = client.get("/api/weather", params={"demo": True, "scenario": "dry"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_demo"] is True
    assert body["source"] == "demo"
    assert "DEMO" in body["message"]


def test_weather_requires_location_or_coords():
    r = client.get("/api/weather")
    assert r.status_code == 422


def _rec(**field_overrides):
    f = {
        "field_name": "API test field",
        "crop_id": "wheat",
        "growth_stage": "flowering",
        "soil_type": "loamy",
        "area_ha": 1.0,
        "irrigation_method": "drip",
        "available_water_l": 100000,
    }
    f.update(field_overrides)
    return {"field": f, "weather_override": {"et0_mm": 6.0, "rainfall_mm": 0.0,
                                             "label": "test", "is_demo": True}}


def test_recommendation_irrigate_now():
    r = client.post("/api/recommendation", json=_rec())
    assert r.status_code == 200
    assert r.json()["recommendation"]["recommendation"] == "Irrigate Now"


def _scenario_field(scenario_id):
    """Reproduce a scenario exactly as a presenter would: its own field + weather."""
    scenarios = client.get("/api/scenarios").json()["scenarios"]
    match = next(s for s in scenarios if s["id"] == scenario_id)
    return match["field"]


def test_recommendation_scenario_dry():
    r = client.post("/api/recommendation", json={"field": _scenario_field("dry"),
                                                 "demo": True, "scenario": "dry"})
    assert r.status_code == 200
    assert r.json()["recommendation"]["recommendation"] == "Irrigate Now"


def test_recommendation_scenario_rain_waits():
    r = client.post("/api/recommendation", json={"field": _scenario_field("rain"),
                                                 "demo": True, "scenario": "rain"})
    assert r.status_code == 200
    assert r.json()["recommendation"]["recommendation"] == "Wait and Reassess"


def test_recommendation_scenario_scarcity_inspects():
    r = client.post("/api/recommendation", json={"field": _scenario_field("scarcity"),
                                                 "demo": True, "scenario": "scarcity"})
    assert r.status_code == 200
    body = r.json()["recommendation"]
    assert body["recommendation"] == "Inspect Field / More Data Needed"
    assert body["metrics"]["water_status"] == "insufficient"


def test_recommendation_negative_area_is_422():
    r = client.post("/api/recommendation", json=_rec(area_ha=-2))
    assert r.status_code == 422


def test_recommendation_returns_weather_when_live_path_used():
    # No override -> weather layer runs; falls back to labelled demo without network.
    r = client.post("/api/recommendation", json={"field": _rec()["field"], "demo": True,
                                                 "scenario": "dry"})
    assert r.json()["weather"]["is_demo"] is True
