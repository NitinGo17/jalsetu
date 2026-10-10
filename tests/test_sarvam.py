"""
Sarvam integration tests.

These run WITHOUT an API key on purpose: the point is to prove that every
Sarvam endpoint degrades cleanly (503, structured error) when the key is
absent, so the app never breaks. Live calls are not made here.
"""

import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)


def test_status_reports_not_configured_and_never_leaks_a_key():
    r = client.get("/api/sarvam/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    # The response must not contain a key field with a value.
    assert "api_key" not in body
    assert len(body["languages"]) == 6
    assert {l["code"] for l in body["languages"]} >= {"en-IN", "hi-IN", "ta-IN"}


def test_translate_without_key_is_503_not_configured():
    r = client.post("/api/translate", json={
        "text": "Irrigate now", "target_language_code": "hi-IN"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "not_configured"


def test_tts_without_key_is_503():
    r = client.post("/api/tts", json={"text": "नमस्ते", "language_code": "hi-IN"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "not_configured"


def test_chat_without_key_is_503():
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "When should I water my wheat?"}],
        "language_code": "en-IN"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "not_configured"


def test_vision_without_key_is_503():
    files = {"file": ("leaf.jpg", b"\xff\xd8\xff\xe0notarealimage", "image/jpeg")}
    r = client.post("/api/vision", files=files, data={"question": "what is this?"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "not_configured"


def test_stt_without_key_is_503():
    files = {"file": ("clip.webm", b"notarealaudio", "audio/webm")}
    r = client.post("/api/stt", files=files)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "not_configured"


def test_translate_validation_rejects_empty_text():
    r = client.post("/api/translate", json={"text": "", "target_language_code": "hi-IN"})
    assert r.status_code == 422


def test_vision_rejects_non_image_before_any_api_call():
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    r = client.post("/api/vision", files=files)
    assert r.status_code == 422


def test_chat_rejects_unknown_role():
    r = client.post("/api/chat", json={
        "messages": [{"role": "system", "content": "hack"}], "language_code": "en-IN"})
    assert r.status_code == 422


def test_system_prompt_contains_safety_rules():
    from backend.sarvam import build_system_prompt
    p = build_system_prompt("hi-IN", {"crop": "wheat", "recommendation": "Irrigate Now"})
    assert "NEVER give a pesticide" in p
    assert "hi-IN" in p
    assert "wheat" in p
    # The key is never part of any prompt.
    assert "api-subscription" not in p.lower()


def test_chat_payload_disables_reasoning_and_leaves_headroom():
    """Regression guard: with reasoning ON and a small max_tokens, sarvam-105b
    spent the whole budget on reasoning and returned EMPTY content."""
    from backend.sarvam import build_chat_payload
    payload = build_chat_payload([{"role": "user", "content": "hi"}], "hi-IN")
    assert payload["reasoning_effort"] is None, "reasoning must be disabled by default"
    assert payload["max_tokens"] >= 800, "need headroom so replies are not empty"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][-1] == {"role": "user", "content": "hi"}
    assert "NEVER give a pesticide" in payload["messages"][0]["content"]
