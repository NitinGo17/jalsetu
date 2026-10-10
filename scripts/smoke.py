"""
Smoke test: start the real server as a managed subprocess, exercise the HTTP
surface end to end, then shut it down. Run with:

    python scripts/smoke.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PORT = 8137
BASE = f"http://127.0.0.1:{PORT}"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  — " + detail) if detail else ""))


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        # Wait for the server to accept connections.
        ready = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                httpx.get(BASE + "/api/health", timeout=1.0)
                ready = True
                break
            except Exception:
                time.sleep(0.5)
        if not ready:
            out = ""
            try:
                out = proc.stdout.read() if proc.stdout else ""
            except Exception:
                pass
            print("Server did not start. Output:\n" + out)
            return 1

        with httpx.Client(base_url=BASE, timeout=20.0) as c:
            # 1. Health
            r = c.get("/api/health")
            check("GET /api/health", r.status_code == 200 and r.json()["status"] == "ok")

            # 2. Static pages
            r = c.get("/")
            check("GET / (landing)", r.status_code == 200 and "Smarter Irrigation" in r.text)
            r = c.get("/app")
            check("GET /app (dashboard)", r.status_code == 200 and "view-dashboard" in r.text)
            r = c.get("/style.css")
            check("GET /style.css", r.status_code == 200 and "--forest-900" in r.text)
            r = c.get("/app.js")
            check("GET /app.js", r.status_code == 200 and "apiFetch" in r.text)
            r = c.get("/i18n.js")
            check("GET /i18n.js (6 languages)", r.status_code == 200 and r.text.count("'nav.dashboard'") >= 6)
            r = c.get("/assets/hero-farm.jpg")
            check("GET /assets/hero-farm.jpg", r.status_code == 200 and len(r.content) > 10000)
            r = c.get("/ATTRIBUTION.md")
            check("GET /ATTRIBUTION.md", r.status_code == 200 and "Licence" in r.text)

            # Sarvam is unconfigured by design here; the status must say so, cleanly.
            r = c.get("/api/sarvam/status")
            check("GET /api/sarvam/status (unconfigured)", r.status_code == 200
                  and r.json()["configured"] is False and len(r.json()["languages"]) == 6)
            r = c.post("/api/translate", json={"text": "hi", "target_language_code": "hi-IN"})
            check("POST /api/translate without key -> 503", r.status_code == 503
                  and r.json()["detail"]["code"] == "not_configured")

            # 3. Reference data
            r = c.get("/api/crops")
            check("GET /api/crops", r.status_code == 200 and r.json()["count"] >= 10)
            r = c.get("/api/meta")
            check("GET /api/meta", r.status_code == 200 and len(r.json()["irrigation_methods"]) == 4)
            r = c.get("/api/scenarios")
            scen = r.json()["scenarios"]
            check("GET /api/scenarios", r.status_code == 200 and len(scen) == 3)

            # 4. Weather (demo, no network dependency)
            r = c.get("/api/weather", params={"demo": "true", "scenario": "dry"})
            body = r.json()
            check("GET /api/weather (demo)", r.status_code == 200 and body["is_demo"] is True)
            r = c.get("/api/weather")
            check("GET /api/weather (no location -> 422)", r.status_code == 422)

            # 5. Recommendation across the three scenarios, using each scenario's field.
            expected = {"dry": "Irrigate Now", "rain": "Wait and Reassess",
                        "scarcity": "Inspect Field / More Data Needed"}
            for s in scen:
                payload = {"field": s["field"], "demo": True, "scenario": s["id"]}
                r = c.post("/api/recommendation", json=payload)
                rec = r.json()["recommendation"]
                got = rec["recommendation"]
                check(f"POST /api/recommendation [{s['id']}] -> {expected[s['id']]}",
                      r.status_code == 200 and got == expected[s["id"]], "got: " + got)
                # internal consistency (rounded display values, so allow 1%)
                b = rec["breakdown"]
                vol = b["net_irrigation_mm"] * b["area_ha"] * 10000
                rel = abs(b["net_volume_l"] - vol) / max(1.0, abs(vol))
                ok = (abs(b["crop_water_demand_mm"] - b["et0_mm"] * b["kc"]) < 0.02
                      and abs(b["net_irrigation_mm"] - (b["crop_water_demand_mm"] - b["effective_rainfall_mm"])) < 0.02
                      and rel < 0.01)
                check(f"   consistency [{s['id']}]", ok, f"rel_vol_err={rel:.4f}")

            # 6. Live weather path (network; informational — fallback allowed)
            r = c.post("/api/recommendation", json={
                "field": {"field_name": "Live test", "crop_id": "wheat", "growth_stage": "flowering",
                          "soil_type": "loamy", "area_ha": 1.0, "irrigation_method": "drip",
                          "available_water_l": 100000},
                "location": "Prayagraj, Uttar Pradesh"})
            if r.status_code == 200:
                w = r.json()["weather"]
                check("POST /api/recommendation (live location)", True,
                      f"source={w['source']} is_demo={w['is_demo']}")
            else:
                check("POST /api/recommendation (live location)", False, str(r.status_code))

            # 7. Validation
            r = c.post("/api/recommendation", json={"field": {
                "field_name": "bad", "crop_id": "wheat", "growth_stage": "flowering",
                "soil_type": "loamy", "area_ha": -1, "irrigation_method": "drip"}})
            check("POST invalid area -> 422", r.status_code == 422)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
