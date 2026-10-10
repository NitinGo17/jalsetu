"""
main.py
-------
JalSetu API — FastAPI application.

Routes are thin: they validate input, delegate to the engine in
backend/irrigation.py and the weather layer in backend/weather.py, and return
structured JSON. Business logic lives in those modules, not here.

Endpoints
---------
GET  /api/health          service liveness + metadata
GET  /api/crops           crop reference data (Kc by growth stage)
GET  /api/meta            irrigation methods, soil types, stages, efficiencies
GET  /api/scenarios       the three deterministic demo scenarios
GET  /api/weather         forecast for a location (live, with labelled fallback)
POST /api/recommendation  full irrigation recommendation for a field

The frontend is served from ../frontend at "/".
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend import crop_data, irrigation, sarvam, weather

APP_VERSION = "2.2.0"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="JalSetu API",
    description="Intelligent irrigation decision-support for Indian farmers.",
    version=APP_VERSION,
)

# Local-development CORS. The MVP has no auth and no cookies, so a permissive
# policy is safe here; tighten to specific origins before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models (Pydantic validation)
# ---------------------------------------------------------------------------
class FieldModel(BaseModel):
    field_name: str = Field(default="Unnamed field", max_length=120)
    crop_id: str = Field(min_length=1, max_length=40)
    growth_stage: str = Field(min_length=1, max_length=40)
    soil_type: str = Field(min_length=1, max_length=40)
    area_ha: float = Field(ge=0, le=10000, description="Field area in hectares")
    irrigation_method: str = Field(min_length=1, max_length=40)
    available_water_l: Optional[float] = Field(
        default=None, ge=0, le=1_000_000_000,
        description="Water the farmer can actually apply, in litres",
    )

    @field_validator("crop_id", "growth_stage", "soil_type", "irrigation_method")
    @classmethod
    def _strip_lower(cls, v: str) -> str:
        return v.strip().lower()


class WeatherOverride(BaseModel):
    et0_mm: float = Field(ge=0, le=30)
    rainfall_mm: float = Field(default=0.0, ge=0, le=1000)
    label: str = Field(default="Manual weather input", max_length=160)
    is_demo: bool = True


class RecommendationRequest(BaseModel):
    field: FieldModel
    location: Optional[str] = Field(default=None, max_length=160)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    demo: bool = False
    scenario: Optional[str] = Field(default=None, max_length=40)
    weather_override: Optional[WeatherOverride] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "JalSetu API",
        "version": APP_VERSION,
        "time_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "engine": "deterministic (no randomness, no database)",
    }


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
@app.get("/api/crops")
async def crops() -> Dict[str, Any]:
    return {
        "count": len(crop_data.CROPS),
        "growth_stages": [
            {"id": s, "label": crop_data.GROWTH_STAGE_LABELS[s]}
            for s in crop_data.GROWTH_STAGES
        ],
        "crops": crop_data.list_crops(),
        "source_note": (
            "Kc values are indicative reference values from FAO-56 (Allen et al., "
            "1998), Table 12. The 'vegetative' value is a JalSetu interpolation "
            "(60% from initial to mid-season Kc), not a published FAO figure."
        ),
    }


@app.get("/api/meta")
async def meta() -> Dict[str, Any]:
    return {
        "irrigation_methods": [
            {
                "id": m,
                "label": irrigation.IRRIGATION_METHOD_LABELS[m],
                "efficiency": e,
            }
            for m, e in irrigation.IRRIGATION_EFFICIENCY.items()
        ],
        "soil_types": [
            {"id": s, "label": s.capitalize(), "note": irrigation.SOIL_NOTES.get(s, "")}
            for s in irrigation.SOIL_TYPES
        ],
        "growth_stages": [
            {"id": s, "label": crop_data.GROWTH_STAGE_LABELS[s]}
            for s in crop_data.GROWTH_STAGES
        ],
        "conversion": "1 mm over 1 hectare = 10,000 litres",
        "negligible_irrigation_mm": irrigation.NEGLIGIBLE_IRRIGATION_MM,
        "recommendation_states": [
            irrigation.RECOMMENDATION_IRRIGATE,
            irrigation.RECOMMENDATION_WAIT,
            irrigation.RECOMMENDATION_INSPECT,
        ],
    }


@app.get("/api/scenarios")
async def scenarios() -> Dict[str, Any]:
    return {
        "scenarios": [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "field": s["field"],
                "weather": {
                    "et0_mm": s["weather"]["et0_mm"],
                    "rainfall_mm": s["weather"]["rainfall_mm"],
                },
            }
            for s in weather.DEMO_SCENARIOS
        ],
        "note": "Deterministic demo scenarios. They do not depend on live weather.",
    }


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
@app.get("/api/weather")
async def get_weather(
    location: Optional[str] = Query(default=None),
    latitude: Optional[float] = Query(default=None, ge=-90, le=90),
    longitude: Optional[float] = Query(default=None, ge=-180, le=180),
    demo: bool = Query(default=False),
    scenario: Optional[str] = Query(default=None),
    allow_fallback: bool = Query(default=True),
) -> Dict[str, Any]:
    if not demo and not location and (latitude is None or longitude is None):
        raise HTTPException(
            status_code=422,
            detail="Provide 'location', or both 'latitude' and 'longitude', "
                   "or set demo=true.",
        )
    try:
        return await weather.get_weather(
            location=location,
            latitude=latitude,
            longitude=longitude,
            demo=demo,
            scenario=scenario,
            allow_fallback=allow_fallback,
        )
    except weather.WeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------
def _weather_to_input(w: Dict[str, Any], fallback_label: str) -> irrigation.WeatherInput:
    planning = w.get("planning_day") or {}
    return irrigation.WeatherInput(
        et0_mm=planning.get("et0_mm"),
        rainfall_mm=planning.get("rainfall_mm"),
        source=w.get("source", "unknown"),
        label=w.get("message", fallback_label),
        planning_date=planning.get("date"),
        is_demo=bool(w.get("is_demo")),
        extra={"provider": w.get("provider")},
    )


@app.post("/api/recommendation")
async def recommendation(req: RecommendationRequest) -> Dict[str, Any]:
    field = irrigation.FieldInput(
        crop_id=req.field.crop_id,
        growth_stage=req.field.growth_stage,
        soil_type=req.field.soil_type,
        area_ha=req.field.area_ha,
        irrigation_method=req.field.irrigation_method,
        available_water_l=req.field.available_water_l,
        field_name=req.field.field_name,
    )

    # Resolve weather: explicit override > demo scenario > live lookup.
    weather_payload: Optional[Dict[str, Any]] = None
    if req.weather_override is not None:
        wo = req.weather_override
        weather_input = irrigation.WeatherInput(
            et0_mm=wo.et0_mm,
            rainfall_mm=wo.rainfall_mm,
            source="demo" if wo.is_demo else "manual",
            label=wo.label,
            is_demo=wo.is_demo,
        )
    else:
        try:
            weather_payload = await weather.get_weather(
                location=req.location,
                latitude=req.latitude,
                longitude=req.longitude,
                demo=req.demo or bool(req.scenario),
                scenario=req.scenario,
                allow_fallback=True,
            )
        except weather.WeatherError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        weather_input = _weather_to_input(weather_payload, "Weather data")

    result = irrigation.calculate(field, weather_input)
    return {
        "status": "ok",
        "recommendation": result,
        "weather": weather_payload,
    }


# ---------------------------------------------------------------------------
# Sarvam AI (translation, speech, assistant, photo) — server-side proxy
# ---------------------------------------------------------------------------
def _sarvam_http(exc: sarvam.SarvamError) -> HTTPException:
    return HTTPException(
        status_code=exc.status or 502,
        detail={"message": str(exc), "code": exc.code},
    )


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    target_language_code: str = Field(min_length=2, max_length=10)
    source_language_code: str = Field(default="auto", max_length=10)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2400)
    language_code: str = Field(default="hi-IN", max_length=10)
    speaker: Optional[str] = Field(default=None, max_length=40)


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(min_length=1, max_length=20)
    language_code: str = Field(default="en-IN", max_length=10)
    context: Optional[Dict[str, Any]] = None


@app.get("/api/sarvam/status")
async def sarvam_status() -> Dict[str, Any]:
    """Whether Sarvam is configured. Never reveals the key."""
    return sarvam.status()


@app.post("/api/translate")
async def translate(req: TranslateRequest) -> Dict[str, Any]:
    try:
        out = await sarvam.translate(
            req.text, req.target_language_code, req.source_language_code
        )
        return {"translated_text": out, "target_language_code": req.target_language_code}
    except sarvam.SarvamError as exc:
        raise _sarvam_http(exc) from exc


@app.post("/api/tts")
async def tts(req: TTSRequest) -> Dict[str, Any]:
    try:
        audio = await sarvam.text_to_speech(req.text, req.language_code, req.speaker)
        return audio
    except sarvam.SarvamError as exc:
        raise _sarvam_http(exc) from exc


@app.post("/api/stt")
async def stt(
    file: UploadFile = File(...),
    language_code: str = Form(default="unknown"),
    mode: str = Form(default="transcribe"),
) -> Dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty audio file.")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio too large (max 12 MB).")
    try:
        return await sarvam.speech_to_text(
            data, file.filename or "audio.webm",
            file.content_type or "audio/webm", mode=mode, language_code=language_code,
        )
    except sarvam.SarvamError as exc:
        raise _sarvam_http(exc) from exc


@app.post("/api/chat")
async def chat(req: ChatRequest) -> Dict[str, Any]:
    try:
        reply = await sarvam.chat(
            [m.model_dump() for m in req.messages],
            language_code=req.language_code,
            context=req.context,
        )
        return {"reply": reply}
    except sarvam.SarvamError as exc:
        raise _sarvam_http(exc) from exc


@app.post("/api/vision")
async def vision(
    file: UploadFile = File(...),
    question: str = Form(default=""),
    language_code: str = Form(default="en-IN"),
) -> Dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty image file.")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="Upload an image file.")
    try:
        answer = await sarvam.vision_chat(
            data, file.content_type or "image/jpeg",
            question=question, language_code=language_code,
        )
        return {"answer": answer}
    except sarvam.SarvamError as exc:
        raise _sarvam_http(exc) from exc


# ---------------------------------------------------------------------------
# Frontend hosting
# ---------------------------------------------------------------------------
@app.get("/app")
async def app_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.html")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
