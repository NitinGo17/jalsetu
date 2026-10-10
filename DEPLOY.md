# Deploying JalSetu

JalSetu is a **Python FastAPI** service that also serves the front end, so it
needs a host that runs Python. That rules out static-only platforms.

| Host | Can it run JalSetu? | Notes |
|---|---|---|
| **Render** | ✅ Yes — easiest | Free tier. Uses `render.yaml` in this repo. |
| **Railway** | ✅ Yes | Uses the `Dockerfile`. |
| **Fly.io** | ✅ Yes | Uses the `Dockerfile`. |
| **Hugging Face Spaces** | ✅ Yes | Docker SDK. |
| Netlify | ❌ No | Static sites + JS/Go functions only. Cannot run FastAPI. |
| Cloudflare Pages / Workers | ❌ No | No ASGI/Python runtime for FastAPI. |
| GitHub Pages | ❌ No | Static files only. |

---

## Option 1 — Render (recommended, free)

1. Push this repo to GitHub (public is fine).
2. Sign in at **render.com** → **New +** → **Blueprint**.
3. Pick this repository. Render reads `render.yaml` and configures everything.
4. When it asks for the **`SARVAM_API_KEY`** environment variable, paste your key.
   (This is why the key is never in the repo — it is entered here, once.)
5. Click **Apply**. First build takes a few minutes.
6. Open the URL Render gives you. Landing page at `/`, app at `/app`.

Check it worked: `https://<your-app>.onrender.com/api/sarvam/status` should show
`"configured": true`.

> Render's free tier sleeps after inactivity, so the first request after a pause
> takes a few seconds to wake. That is normal.

## Option 2 — Docker (Railway, Fly.io, HF Spaces, anywhere)

```bash
docker build -t jalsetu .
docker run -p 8000:8000 -e SARVAM_API_KEY=sk_your_key_here jalsetu
```

Then open `http://localhost:8000`. On a host, set `SARVAM_API_KEY` as a secret
environment variable in that host's dashboard — never in the image or the repo.

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SARVAM_API_KEY` | No | Enables translation, speech, assistant. Without it those features show a clear "not switched on yet" notice; everything else still works. |
| `PORT` | Set by the host | The port uvicorn binds to. |
| `SARVAM_BASE_URL` | No | Defaults to `https://api.sarvam.ai`. |
| `SARVAM_CHAT_MODEL` | No | Defaults to `sarvam-105b`. |
| `SARVAM_VISION_MODEL` | No | Defaults to `gemma4` (needs beta access). |
| `SARVAM_TTS_MODEL` / `SARVAM_STT_MODEL` | No | Defaults to `bulbul:v3` / `saaras:v3`. |

---

## Rules that keep this safe

- **Never commit `.env`.** It is in `.gitignore`.
- **Never put the key in the repo, the Dockerfile, or any front-end file.** The
  key is read server-side only and is never sent to the browser.
- Set the key in the host's dashboard as a secret, not in a committed config.
- Rotate any key that has ever been shared in a screenshot or a chat.
