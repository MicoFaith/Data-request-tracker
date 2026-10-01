"""Optional React assets; server-rendered pages remain a no-JavaScript fallback."""

import json

from django.conf import settings


def assets(request):
    manifest = settings.BASE_DIR / "static/react/.vite/manifest.json"
    if not manifest.exists():
        return {}
    entry = json.loads(manifest.read_text(encoding="utf-8"))["src/main.jsx"]
    return {
        "react_js": "react/" + entry["file"],
        "react_css": ["react/" + name for name in entry.get("css", [])],
    }
