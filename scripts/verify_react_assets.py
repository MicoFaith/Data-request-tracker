"""HTTP checks for the built React assets; not a visual browser test."""

import re
import urllib.request

BASE = "http://127.0.0.1:8000"


def fetch(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as response:
        assert response.status == 200
        return response.read().decode("utf-8"), response.headers


html, _ = fetch("/login/")
entry = re.search(r'<script type="module" src="([^"]+)"', html)
assert entry, "React entry script missing; rebuild the Docker image."
assert "vendor/htmx.min.js" not in html, "Two frontend routers must not run together."
js, headers = fetch(entry[1])
assert "javascript" in headers["Content-Type"] and len(js) > 1000
for css in re.findall(r'<link rel="stylesheet" href="([^"]+)"', html):
    content, headers = fetch(css)
    assert "text/css" in headers["Content-Type"] and content
chunks = set(re.findall(r'["\']\./(staff-[^"\']+\.js)["\']', js))
assert chunks, "Lazy staff route chunk missing."
for chunk in chunks:
    content, headers = fetch("/static/react/assets/" + chunk)
    assert "javascript" in headers["Content-Type"] and content
print("PASS: React entry, stylesheets and staff route chunk served over HTTP.")
print("Visual layout and real-browser interactions require separate browser checks.")
