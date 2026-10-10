"""
Fetch openly-licensed images from Wikimedia Commons for JalSetu.

Prefers CC0 / public-domain; falls back to CC BY-SA with full attribution.
Writes images to frontend/assets/ and a CREDITS file next to them.

    python scripts/fetch_images.py
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "frontend" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

API = "https://commons.wikimedia.org/w/api.php"
UA = "JalSetuHackathon/1.0 (educational prototype)"

# term -> output filename
TERMS = {
    "farmer India field": "hero-farm.jpg",
    "wheat field India": "crop-wheat.jpg",
    "paddy field India": "crop-paddy.jpg",
    "maize field India": "crop-maize.jpg",
    "cotton field India": "crop-cotton.jpg",
    "drip irrigation India": "irrigation-drip.jpg",
    "soil hands India": "soil-hands.jpg",
    "seeds sowing India": "seeds-sowing.jpg",
}

PREFERRED = ["cc0", "public domain", "pd"]


def api_get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def clean(text):
    return re.sub("<[^>]+>", "", text or "").strip()


def search(term):
    data = api_get({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {term}", "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1400,
    })
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata") or {}
        lic = clean((em.get("LicenseShortName") or {}).get("value", ""))
        artist = clean((em.get("Artist") or {}).get("value", ""))
        url = (ii.get("thumburl") or ii.get("url") or "").split("?")[0]
        if not url:
            continue
        out.append({"title": p.get("title", ""), "license": lic,
                    "artist": artist, "url": url})
    return out


def pick(candidates):
    """Prefer CC0 / public domain, else the first CC BY-SA."""
    for c in candidates:
        low = c["license"].lower()
        if any(k in low for k in PREFERRED):
            return c
    for c in candidates:
        if "cc by" in c["license"].lower():
            return c
    return candidates[0] if candidates else None


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.write_bytes(data)
    return len(data)


def main():
    credits = []
    for term, fname in TERMS.items():
        try:
            cands = search(term)
            chosen = pick(cands)
            if not chosen:
                print(f"  no result for {term}")
                continue
            size = download(chosen["url"], ASSETS / fname)
            credits.append((fname, chosen))
            print(f"  {fname}: {chosen['license']} — {chosen['title']} ({size//1024} KB)")
        except Exception as e:
            print(f"  FAILED {term}: {e}")

    lines = [
        "# Image credits",
        "",
        "JalSetu uses openly-licensed photographs from Wikimedia Commons. Images are",
        "used under the licence shown below. Files live in `frontend/assets/`.",
        "",
    ]
    for fname, c in credits:
        lines.append(f"## {fname}")
        lines.append(f"- Source: Wikimedia Commons — {c['title']}")
        lines.append(f"- Licence: {c['license']}")
        lines.append(f"- Author: {c['artist'] or 'see Commons page'}")
        lines.append(f"- URL: {c['url']}")
        lines.append("")
    lines.append("Images under CC BY-SA remain under that licence; if you reuse them,")
    lines.append("keep this attribution. CC0 / public-domain images carry no conditions.")
    (ROOT / "ATTRIBUTION.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {len(credits)} images and ATTRIBUTION.md")


if __name__ == "__main__":
    main()
