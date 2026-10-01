"""Verify all five supplied users through real HTTP API and HTML form requests.

Run after run.py. Each run adds two requests, eight test episodes and one
deactivated test user. Existing accounts and assignments are unchanged.
This checks server-rendered UI flows, not browser JavaScript or appearance.
"""

import csv
import io
import secrets
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smoke_test import BASE, Session


class WebSession(Session):
    def token(self):
        return next(c.value for c in self.cookies if c.name == "csrftoken")

    def html(self, path, fields=None, expected=200, upload=None):
        headers = {}
        payload = None
        if upload is not None:
            boundary = "desk" + secrets.token_hex(16)
            payload = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                'filename="test.csv"\r\nContent-Type: text/csv\r\n\r\n'
            ).encode() + upload + f"\r\n--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif fields is not None:
            payload = urllib.parse.urlencode({
                **fields, "csrfmiddlewaretoken": self.token()
            }).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if payload is not None:
            headers["X-CSRFToken"] = self.token()
        req = urllib.request.Request(BASE + path, data=payload, headers=headers)
        try:
            response = self.opener.open(req, timeout=20)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            text = response.read().decode()
            assert response.code == expected, (path, response.code, text[:300])
            return text, response.geturl()

    def upload(self, payload, expected=200):
        import json
        return json.loads(self.html("/api/episodes/import/", upload=payload,
                                    expected=expected)[0])


def main():
    sessions = []
    for email, password, role in [
        ("client-a@example.com", "client123", "client"),
        ("client-b@example.com", "client123", "client"),
        ("ops1@example.com", "ops123", "operator"),
        ("ops2@example.com", "ops123", "operator"),
        ("admin@example.com", "admin123", "admin"),
    ]:
        session = WebSession(email, password)
        # Exercise HTML login as well as the API login in Session.__init__.
        session.html("/logout/", {})
        session.html("/login/", {"email": email, "password": password})
        session.user = session.call("/api/me/")["user"]
        assert session.user["email"] == email and session.user["role"] == role
        session.html("/")
        session.call("/health")
        session.html("/users/", expected=200 if role == "admin" else 403)
        session.call("/api/users/", expected=200 if role == "admin" else 403)
        for path in ["/episodes/", "/analytics/"]:
            session.html(path, expected=403 if role == "client" else 200)
        session.html("/requests/new/", expected=200 if role == "client" else 403)
        sessions.append(session)
    a, b, ops1, ops2, admin = sessions
    print("PASS: API/HTML login and role-specific pages for all five supplied users")

    now = datetime.now(ZoneInfo("Africa/Kigali"))
    run_id = str(secrets.randbelow(10**20))
    task = "role verification " + run_id
    eids = [f"EP-{run_id}{n}" for n in range(8)]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["episode_id", "robot_id", "task_name", "recorded_at",
                     "duration_seconds", "operator_name", "quality"])
    for n, eid in enumerate(eids):
        writer.writerow([eid, "arm-01", task if n != 7 else task + " other",
                         now.isoformat(), 30, "HTTP test", "bad" if n == 6 else
                         "usable" if n % 2 else "good"])
    payload = stream.getvalue().encode()
    for client in [a, b]:
        client.upload(payload, expected=403)
    assert ops1.upload(payload)["imported"] == 8
    repeated = ops2.upload(payload)
    assert repeated["imported"] == 0 and repeated["skipped"] == 8
    assert repeated["reasons"] == {"duplicate_episode_id": 8}
    assert "duplicate_episode_id" in ops2.html("/episodes/", upload=payload)[0]
    ops1.upload(b"\xffbad header", expected=422)
    print("PASS: both operators import; repeated import is idempotent; invalid CSV is rejected")

    fields = {"task_name": task, "episodes_requested": 2,
              "deadline": (now.date() + timedelta(days=7)).isoformat(),
              "notes": "All-account HTTP verification"}
    before = a.call("/api/requests/")["total"]
    for deadline in [now.date() - timedelta(days=1), now.date()]:
        invalid = dict(fields, deadline=deadline.isoformat())
        a.call("/api/requests/", invalid, 422)
        assert "Deadline must be a future date" in a.html("/requests/new/", invalid)[0]
    assert a.call("/api/requests/")["total"] == before
    assert f'min="{now.date() + timedelta(days=1)}"' in a.html("/requests/new/")[0]
    _, url = a.html("/requests/new/", fields)
    rid_a = int(urllib.parse.urlparse(url).path.strip("/").split("/")[1])
    rid_b = b.call("/api/requests/", fields, 201)["request"]["id"]
    for owner, other, rid in [(a, b, rid_a), (b, a, rid_b)]:
        assert owner.call(f"/api/requests/{rid}/")["request"]["client_id"] == owner.user["id"]
        other.call(f"/api/requests/{rid}/", expected=404)
        other.html(f"/requests/{rid}/", expected=404)
        other.call(f"/api/requests/{rid}/status/", {"status": "accepted"}, 404)
        assert all(row["client_id"] == owner.user["id"]
                   for row in owner.call("/api/requests/")["requests"])
        owner.call(f"/api/requests/{rid}/status/", {"status": "in_progress"}, 403)
    for staff in [ops1, ops2, admin]:
        ids = {row["id"] for row in staff.call("/api/requests/")["requests"]}
        assert {rid_a, rid_b} <= ids
        staff.call("/api/requests/", fields, 403)

    detail = f"/requests/{rid_a}/"
    ops1.html(detail + "status/", {"status": "in_progress"})
    html, _ = ops1.html(detail + "?quality=usable")
    assert eids[1] in html and eids[0] not in html
    ops1.call(f"/api/requests/{rid_a}/status/", {"status": "delivered"}, 409)
    for eid in eids[6:]:
        ops1.call(f"/api/requests/{rid_a}/assignments/", {"episode_id": eid}, 409)
    for eid in eids[:2]:
        ops1.html(detail + "assign/", {"episode_id": eid})
    ops1.html(detail + "status/", {"status": "delivered"})
    first_delivery = a.call(f"/api/requests/{rid_a}/")["request"]["first_delivered_at"]
    html, _ = a.html(detail)
    assert "Accept delivery" in html and "Reject for rework" in html
    a.html(detail + "status/", {"status": "rejected"})
    ops2.html(detail + "status/", {"status": "in_progress"})
    ops2.html(detail + "assign/", {"episode_id": eids[1], "remove": "true"})
    ops2.html(detail + "assign/", {"episode_id": eids[2]})
    admin.html(detail + "status/", {"status": "delivered"})
    a.html(detail + "status/", {"status": "accepted"})
    result = a.call(f"/api/requests/{rid_a}/")
    assert result["request"]["status"] == "accepted"
    assert result["request"]["first_delivered_at"] == first_delivery
    expected_actors = [a, ops1, ops1, a, ops2, admin, a]
    assert [e["actor_id"] for e in result["history"]] == [s.user["id"] for s in expected_actors]
    assert all(event["at"] for event in result["history"])
    assert {ep["episode_id"] for ep in result["episodes"]} == {eids[0], eids[2]}

    api_path = f"/api/requests/{rid_b}/"
    ops2.call(api_path + "status/", {"status": "in_progress"})
    ops2.call(api_path + "assignments/", {"episode_id": eids[0]}, 409)
    for eid in [eids[1], eids[3]]:
        ops2.call(api_path + "assignments/", {"episode_id": eid}, 201)
    ops2.call(api_path + "status/", {"status": "delivered"})
    for staff in [ops1, ops2, admin]:
        staff.call(api_path + "status/", {"status": "accepted"}, 403)
    b.call(api_path + "status/", {"status": "accepted"})
    assert b.call(api_path)["request"]["status"] == "accepted"
    print(f"PASS: both clients, both operators, HTML/API delivery and rework, isolation, assignment rules and audit (requests #{rid_a}, #{rid_b})")

    email = f"smoke-{run_id}@example.com"
    password = secrets.token_urlsafe(24)
    created = admin.call("/api/users/", {"email": email, "name": "HTTP verification",
                         "role": "client", "password": password}, 201)["user"]
    try:
        temporary = WebSession(email, password)
        temporary.call("/api/episodes/", expected=403)
        admin.html("/users/", {"user_id": created["id"], "role": "operator", "is_active": "true"})
        temporary.call("/api/episodes/")
    finally:
        admin.html("/users/", {"user_id": created["id"], "role": "operator"})
    temporary.call("/api/me/", expected=401)
    temporary.call("/api/login/", {"email": email, "password": password}, 401)
    print("PASS: admin creates a user, changes role and deactivates; existing sessions observe changes")

    for staff in [ops1, ops2, admin]:
        stats = staff.call(f"/api/analytics/?start={now.date()}&end={now.date()}")
        assert stats["request_fulfilment"]["counts_by_status"]["accepted"] >= 2
        assert stats["request_fulfilment"]["median_seconds_submitted_to_first_delivered"] is not None
        assert len(stats["top_5_good_tasks"]) <= 5
        assert sum(row["count"] for row in stats["episodes_per_day_per_robot"]) >= 8
    for session in sessions:
        session.html("/logout/", {})
        session.call("/api/me/", expected=401)
    print("PASS: analytics, authenticated health and logout for all roles")


if __name__ == "__main__":
    main()
