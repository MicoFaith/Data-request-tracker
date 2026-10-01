"""Check notification isolation on the local running demo; creates one request."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smoke_test import BASE, Session


def main():
    sessions = {
        "a": Session("client-a@example.com", "client123"),
        "b": Session("client-b@example.com", "client123"),
        "operator": Session("ops1@example.com", "ops123"),
        "admin": Session("admin@example.com", "admin123"),
    }
    try:
        deadline = datetime.now(ZoneInfo("Africa/Kigali")).date() + timedelta(days=7)
        request = sessions["a"].call(
            "/api/requests/",
            {
                "task_name": "pick cup",
                "episodes_requested": 1,
                "deadline": deadline.isoformat(),
                "notes": "Notification HTTP verification",
            },
            201,
        )["request"]
        title = f"Request #{request['id']} submitted"
        found = {}
        for role, session in sessions.items():
            rows = session.call("/api/notifications/")["notifications"]
            matching = [row for row in rows if row["title"] == title]
            assert bool(matching) == (role != "b"), (role, matching)
            if matching:
                found[role] = matching[0]
            assert session.opener.open(BASE + "/notifications/").code == 200
        sessions["b"].call("/api/notifications/", {"id": found["a"]["id"]}, 404)
        sessions["a"].call("/api/notifications/", {"id": found["a"]["id"]})
        rows = sessions["a"].call("/api/notifications/?unread=true")["notifications"]
        assert not any(row["id"] == found["a"]["id"] for row in rows)
        rows = sessions["admin"].call("/api/notifications/?unread=true")[
            "notifications"
        ]
        assert any(row["id"] == found["admin"]["id"] for row in rows)
        sessions["operator"].call(
            f"/api/requests/{request['id']}/status/", {"status": "in_progress"}
        )
        rows = sessions["a"].call("/api/notifications/")["notifications"]
        assert rows[0]["title"] == f"Request #{request['id']}: in progress"
        preferences = sessions["a"].call("/api/notifications/preferences/")
        assert type(preferences["email_available"]) is bool
        print(
            f"PASS: live notification recipients, ownership, read state, status updates and deep links (request #{request['id']})."
        )
    finally:
        for session in sessions.values():
            session.call("/api/logout/", {})


if __name__ == "__main__":
    main()
