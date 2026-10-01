"""Exercise real HTTP sessions, CSRF, ownership, assignment and review on a local demo.
Run after startup: python scripts/smoke_test.py
This intentionally creates a request in the demo database.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


class Session:
    def __init__(self, email, password):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.opener.open(BASE + "/login/").read()
        self.call("/api/login/", {"email": email, "password": password})

    def call(self, path, data=None, expected=200):
        headers = {"Accept": "application/json"}
        payload = None
        if data is not None:
            payload = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
            headers["X-CSRFToken"] = next(
                c.value for c in self.cookies if c.name == "csrftoken"
            )
        req = urllib.request.Request(BASE + path, data=payload, headers=headers)
        try:
            response = self.opener.open(req)
        except urllib.error.HTTPError as exc:
            response = exc
        result = json.loads(response.read())
        assert response.code == expected, (path, response.code, result)
        return result


def main():
    today = datetime.now(ZoneInfo("Africa/Kigali")).date()
    a = Session("client-a@example.com", "client123")
    b = Session("client-b@example.com", "client123")
    ops = Session("ops1@example.com", "ops123")
    req = a.call(
        "/api/requests/",
        {
            "task_name": "pick cup",
            "episodes_requested": 2,
            "deadline": (today + timedelta(days=7)).isoformat(),
            "notes": "Local HTTP smoke test",
        },
        201,
    )["request"]
    rid = req["id"]
    b.call(f"/api/requests/{rid}/", expected=404)
    ops.call(f"/api/requests/{rid}/status/", {"status": "in_progress"})
    ops.call(f"/api/requests/{rid}/status/", {"status": "delivered"}, expected=409)
    candidates = ops.call(
        "/api/episodes/?task_name=pick%20cup&quality=good&available=true"
    )["episodes"]
    assert len(candidates) >= 2, (
        "Need two available good pick-cup episodes; seed a fresh demo database."
    )
    for ep in candidates[:2]:
        ops.call(
            f"/api/requests/{rid}/assignments/", {"episode_id": ep["episode_id"]}, 201
        )
    ops.call(f"/api/requests/{rid}/status/", {"status": "delivered"})
    a.call(f"/api/requests/{rid}/status/", {"status": "rejected"})
    ops.call(f"/api/requests/{rid}/status/", {"status": "in_progress"})
    ops.call(f"/api/requests/{rid}/status/", {"status": "delivered"})
    a.call(f"/api/requests/{rid}/status/", {"status": "accepted"})
    result = a.call(f"/api/requests/{rid}/")
    assert result["request"]["status"] == "accepted"
    assert len(result["history"]) == 7
    ops.call("/health")
    ops.call(f"/api/analytics/?start={today}&end={today}")
    for path in ["/", "/episodes/", "/analytics/", f"/requests/{rid}/"]:
        response = ops.opener.open(BASE + path)
        assert response.code == 200
        assert b"Dataset Request Desk" in response.read()
    print(
        f"PASS: real HTTP login/CSRF, isolation, count guard, assignments, rejection/rework, acceptance, audit, health, analytics and HTML screens (request #{rid})."
    )


if __name__ == "__main__":
    main()
