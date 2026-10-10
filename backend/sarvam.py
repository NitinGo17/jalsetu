"""
sarvam.py
---------
Server-side proxy for Sarvam AI (https://api.sarvam.ai).

Everything Sarvam-related lives here and is called from the backend only. The
API key is read from the environment (SARVAM_API_KEY) and never leaves the
server: it is not sent to the browser, not embedded in any file, and not
logged. If the key is absent the module reports "not configured" cleanly so the
rest of JalSetu keeps working.

Capabilities used:
  - translate        POST /translate              (text translation)
  - text_to_speech   POST /text-to-speech         (Bulbul, base64 audio)
  - speech_to_text   POST /speech-to-text         (Saaras, multipart audio)
  - chat             POST /v1/chat/completions    (sarvam-105b)
  - vision_chat      POST /v2/chat/completions    (gemma4, inline base64 image)

Auth is the `api-subscription-key` header. Sarvam returns HTTP 403 (not 401)
for a bad or missing key.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional

import httpx

SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("SARVAM_TIMEOUT", "45"))

# Models. Kept as constants so they are easy to change in one place.
CHAT_MODEL = os.environ.get("SARVAM_CHAT_MODEL", "sarvam-105b")
VISION_MODEL = os.environ.get("SARVAM_VISION_MODEL", "gemma4")
TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3")
STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")
TTS_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "priya")

# Languages JalSetu offers in the UI.
SUPPORTED_LANGUAGES = [
    {"code": "en-IN", "label": "English", "native": "English"},
    {"code": "hi-IN", "label": "Hindi", "native": "हिन्दी"},
    {"code": "ta-IN", "label": "Tamil", "native": "தமிழ்"},
    {"code": "te-IN", "label": "Telugu", "native": "తెలుగు"},
    {"code": "bn-IN", "label": "Bengali", "native": "বাংলা"},
    {"code": "mr-IN", "label": "Marathi", "native": "मराठी"},
]

MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB, well under Sarvam's per-file limit


class SarvamError(Exception):
    """A Sarvam call failed. `code` mirrors Sarvam's error code where known."""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class SarvamNotConfigured(SarvamError):
    """No API key is set. Callers should surface this, not crash."""

    def __init__(self):
        super().__init__(
            "Sarvam is not configured. Set the SARVAM_API_KEY environment "
            "variable (see README) and restart the server.",
            status=503,
            code="not_configured",
        )


def api_key() -> str:
    """The key, read from the environment only. Never hardcoded."""
    return (os.environ.get("SARVAM_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def _diagnostics(configured: bool) -> Dict[str, Any]:
    """Where JalSetu looked for the key, and what to do next. Never reveals the key."""
    try:
        from backend import dotenv_path
        path = dotenv_path()
        found = path.is_file()
        path_str = str(path)
    except Exception:
        found, path_str = False, None

    if configured:
        hint = "Key loaded. Voice, assistant and photo are available."
    elif not found:
        hint = ("No .env file was found at " + str(path_str) + ". Create it in the "
                "project root (the folder that contains requirements.txt), beside "
                "backend/ and frontend/.")
    else:
        hint = ("A .env file exists at " + str(path_str) + " but no key was read "
                "from it. Check the line reads SARVAM_API_KEY=sk_... , then RESTART "
                "the server: environment variables are only read at startup.")
    return {"env_file": path_str, "env_file_found": found, "hint": hint}


def status() -> Dict[str, Any]:
    """Report configuration without ever revealing the key."""
    configured = is_configured()
    return {
        "configured": configured,
        "base_url": SARVAM_BASE_URL,
        "models": {
            "chat": CHAT_MODEL,
            "vision": VISION_MODEL,
            "tts": TTS_MODEL,
            "stt": STT_MODEL,
        },
        "languages": SUPPORTED_LANGUAGES,
        "diagnostics": _diagnostics(configured),
        "message": (
            "Sarvam is configured. Translation, speech and the assistant are live."
            if configured
            else "Sarvam is not configured. Set SARVAM_API_KEY to enable "
                 "translation, speech and the assistant. JalSetu works without it."
        ),
    }


def _headers(json_body: bool = True) -> Dict[str, str]:
    if not is_configured():
        raise SarvamNotConfigured()
    h = {"api-subscription-key": api_key()}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _raise_for_response(resp: httpx.Response) -> None:
    """Map Sarvam's status codes to clear, non-leaky messages."""
    if resp.status_code < 400:
        return
    code = ""
    message = ""
    try:
        body = resp.json()
        err = body.get("error") or {}
        code = err.get("code", "") or body.get("code", "")
        message = err.get("message", "") or body.get("message", "")
    except Exception:
        message = (resp.text or "")[:200]

    if resp.status_code == 403 or code == "invalid_api_key_error":
        raise SarvamError(
            "Sarvam rejected the API key. Check SARVAM_API_KEY and that the key "
            "is active in the Sarvam dashboard.",
            status=403, code=code or "invalid_api_key_error",
        )
    if resp.status_code == 402 or code == "insufficient_quota_error":
        raise SarvamError(
            "Sarvam account has no credits left. Add credits in the dashboard.",
            status=402, code=code or "insufficient_quota_error",
        )
    if resp.status_code == 429 or code == "rate_limit_exceeded_error":
        raise SarvamError(
            "Sarvam rate limit reached. Wait a moment and try again.",
            status=429, code=code or "rate_limit_exceeded_error",
        )
    if resp.status_code == 400 and "beta" in message.lower():
        raise SarvamError(
            "This Sarvam model needs beta access on your key.",
            status=400, code=code or "beta_access_required",
        )
    raise SarvamError(
        message or f"Sarvam request failed (HTTP {resp.status_code}).",
        status=resp.status_code, code=code or "sarvam_error",
    )


async def _post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{SARVAM_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=_headers())
    except httpx.TimeoutException as exc:
        raise SarvamError("Sarvam request timed out.", status=504, code="timeout") from exc
    except httpx.HTTPError as exc:
        raise SarvamError(f"Could not reach Sarvam: {exc}", status=502, code="network") from exc
    _raise_for_response(resp)
    try:
        return resp.json()
    except ValueError as exc:
        raise SarvamError("Sarvam returned an unreadable response.", 502, "bad_response") from exc


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------
async def translate(text: str, target_language_code: str,
                    source_language_code: str = "auto") -> str:
    payload = {
        "input": text,
        "source_language_code": source_language_code,
        "target_language_code": target_language_code,
    }
    data = await _post_json("/translate", payload)
    return data.get("translated_text", "")


async def translate_many(items: List[str], target_language_code: str,
                         source_language_code: str = "en-IN") -> List[str]:
    """Translate a batch one-by-one (Sarvam /translate takes one input)."""
    out: List[str] = []
    for item in items:
        out.append(await translate(item, target_language_code, source_language_code))
    return out


# ---------------------------------------------------------------------------
# Text to speech
# ---------------------------------------------------------------------------
async def text_to_speech(text: str, language_code: str,
                         speaker: Optional[str] = None) -> Dict[str, str]:
    payload = {
        "text": text[:2400],  # REST cap is 2500 characters
        "language_code": language_code,
        "speaker": speaker or TTS_SPEAKER,
        "model": TTS_MODEL,
    }
    data = await _post_json("/text-to-speech", payload)
    audios = data.get("audios") or []
    if not audios:
        raise SarvamError("Sarvam returned no audio.", 502, "no_audio")
    return {"audio_base64": audios[0], "mime": "audio/mpeg"}


# ---------------------------------------------------------------------------
# Speech to text
# ---------------------------------------------------------------------------
async def speech_to_text(audio: bytes, filename: str, content_type: str,
                         mode: str = "transcribe",
                         language_code: str = "unknown") -> Dict[str, Any]:
    if not is_configured():
        raise SarvamNotConfigured()
    url = f"{SARVAM_BASE_URL}/speech-to-text"
    files = {"file": (filename or "audio.webm", audio, content_type or "audio/webm")}
    data = {"model": STT_MODEL, "mode": mode}
    if language_code and language_code != "unknown":
        data["language_code"] = language_code
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, files=files, data=data, headers=_headers(json_body=False))
    except httpx.TimeoutException as exc:
        raise SarvamError("Speech recognition timed out.", 504, "timeout") from exc
    except httpx.HTTPError as exc:
        raise SarvamError(f"Could not reach Sarvam: {exc}", 502, "network") from exc
    _raise_for_response(resp)
    body = resp.json()
    return {"transcript": body.get("transcript", ""),
            "language_code": body.get("language_code")}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
# The system prompt is where JalSetu's safety and tone rules live.
def build_system_prompt(language_code: str, context: Optional[Dict[str, Any]] = None) -> str:
    base = (
        "You are JalSetu Mitra, a friendly farming helper for small farmers in India. "
        "You help with irrigation, crops, soil, weather and water. "
        "Rules you must follow: "
        "1. Answer in very simple language, in the user's chosen language, short and clear. "
        "2. Avoid technical words. If you must use one, explain it in one plain sentence. "
        "3. NEVER give a pesticide or fertiliser dose or a chemical quantity from a photo. "
        "For any pest, disease or chemical question, tell the farmer to confirm with the "
        "local Krishi Vigyan Kendra (KVK) or agriculture officer before spraying. "
        "4. Do not promise exact water savings or guaranteed results. "
        "5. If you are unsure, say so plainly. Do not invent facts, prices or schemes. "
        "6. Be kind and respectful. Never blame the farmer. "
    )
    if language_code:
        base += f"The user's language code is {language_code}. Reply in that language. "
    if context:
        bits = []
        for key in ("crop", "growth_stage", "location", "recommendation",
                    "net_irrigation_mm", "net_volume_l", "water_status"):
            if context.get(key) is not None:
                bits.append(f"{key}={context[key]}")
        if bits:
            base += ("Current analysis for this field (use it if relevant, but do not "
                     "reveal it as raw data): " + "; ".join(bits) + ". ")
    return base


def build_chat_payload(messages: List[Dict[str, Any]], language_code: str = "en-IN",
                       context: Optional[Dict[str, Any]] = None,
                       temperature: float = 0.3, max_tokens: int = 900,
                       reasoning_effort: Optional[str] = None) -> Dict[str, Any]:
    """
    Build the chat request body.

    `reasoning_effort` is None by default, which DISABLES the model's internal
    reasoning. This matters: on sarvam-105b the default reasoning burns the
    whole token budget, and the reply comes back EMPTY with
    finish_reason='length'. Verified against the live API — with
    reasoning_effort=None the same prompt returns 0 reasoning tokens and a
    clean answer. JalSetu's assistant gives short, simple replies, so it does
    not need heavy reasoning.
    """
    system = {"role": "system", "content": build_system_prompt(language_code, context)}
    return {
        "model": CHAT_MODEL,
        "messages": [system] + messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }


async def chat(messages: List[Dict[str, Any]], language_code: str = "en-IN",
               context: Optional[Dict[str, Any]] = None,
               temperature: float = 0.3, max_tokens: int = 900,
               reasoning_effort: Optional[str] = None) -> str:
    payload = build_chat_payload(messages, language_code, context, temperature,
                                 max_tokens, reasoning_effort)
    data = await _post_json("/v1/chat/completions", payload)
    choices = data.get("choices") or []
    if not choices:
        raise SarvamError("Sarvam returned no reply.", 502, "no_reply")
    content = (choices[0].get("message") or {}).get("content", "") or ""
    if not content.strip():
        # Distinguish an empty reply from a silent failure, and say what to do.
        finish = choices[0].get("finish_reason")
        if finish == "length":
            raise SarvamError(
                "Sarvam returned an empty reply because the model ran out of "
                "tokens on internal reasoning. Try again, or shorten the question.",
                502, "empty_reply_length",
            )
        raise SarvamError("Sarvam returned an empty reply.", 502, "empty_reply")
    return content


# ---------------------------------------------------------------------------
# Vision (image + question) via the multimodal chat model
# ---------------------------------------------------------------------------
VISION_PROMPT = (
    "You are helping an Indian farmer who has sent a photo. Look at it carefully and "
    "answer in very simple language. Describe only what you can actually see. "
    "If it is a crop, say what condition it seems to be in and what the farmer could "
    "check. If it is a fertiliser, pesticide or seed packet, read the text you can see "
    "and explain it simply. "
    "Do NOT state a chemical dose or a pesticide quantity. For any pest or disease, ask "
    "the farmer to confirm with the local KVK or agriculture officer. "
    "If the photo is unclear or you are not sure, say so honestly instead of guessing."
)


async def vision_chat(image: bytes, mime: str, question: str = "",
                      language_code: str = "en-IN") -> str:
    if len(image) > MAX_IMAGE_BYTES:
        raise SarvamError("Image is too large (max 6 MB).", 413, "image_too_large")
    b64 = base64.b64encode(image).decode("ascii")
    data_url = f"data:{mime or 'image/jpeg'};base64,{b64}"
    ask = question.strip() or "What can you see in this photo, and what should I do?"
    content = [
        {"type": "text", "text": VISION_PROMPT + f"\n\nFarmer's question: {ask}"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 700,
    }
    # Images must be inline base64; remote URLs are rejected by Sarvam.
    data = await _post_json("/v2/chat/completions", payload)
    choices = data.get("choices") or []
    if not choices:
        raise SarvamError("Sarvam returned no answer for the photo.", 502, "no_reply")
    return (choices[0].get("message") or {}).get("content", "") or ""
