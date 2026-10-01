"""Live admin name/delete checks using one temporary account, removed at the end."""

import json
import secrets
import urllib.error
import urllib.request

from smoke_test import BASE, Session


def write(session, method, path, values, expected=200):
    csrf = next(c.value for c in session.cookies if c.name == "csrftoken")
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(values).encode(),
        method=method,
        headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
    )
    try:
        response = session.opener.open(request)
    except urllib.error.HTTPError as exc:
        response = exc
    result = json.loads(response.read())
    assert response.code == expected, (method, path, response.code, result)
    return result


admin = Session("admin@example.com", "admin123")
email = f"verify-delete-{secrets.token_hex(6)}@example.com"
password = secrets.token_urlsafe(24)
person = admin.call(
    "/api/users/",
    {
        "email": email,
        "name": "Temporary verification",
        "password": password,
        "role": "client",
    },
    201,
)["user"]
path = f'/api/users/{person["id"]}/'
try:
    user = Session(email, password)
    operator = Session("ops1@example.com", "ops123")
    write(operator, "PATCH", path, {"name": "Denied"}, 403)
    write(operator, "DELETE", path, {"confirm_email": email}, 403)
    write(admin, "PATCH", path, {"name": "  Updated verification name  "})
    assert user.call("/api/me/")["user"]["name"] == "Updated verification name"
    old_email = email
    updated = write(
        admin,
        "PATCH",
        path,
        {
            "email": f"renamed-{secrets.token_hex(6)}@example.com",
            "organisation": "Verification organisation",
        },
    )
    email = updated["user"]["email"]
    assert user.call("/api/me/")["user"]["email"] == email
    user.call("/api/login/", {"email": old_email, "password": password}, expected=401)
    fresh = Session(email, password)
    fresh.call("/api/logout/", {})
    write(admin, "PATCH", path, {"email": "ADMIN@EXAMPLE.COM"}, 409)
    write(admin, "PATCH", path, {"name": "  "}, 422)
    write(admin, "DELETE", path, {"confirm_email": "wrong@example.com"}, 422)
    write(admin, "DELETE", path, {"confirm_email": email})
    user.call("/api/me/", expected=401)
    operator.call("/api/logout/", {})
    print(
        "PASS: full profile edit, new-email login, duplicate/invalid input, operator denial, confirmed deletion and session revocation."
    )
finally:
    # Cleanup is limited to the unused account created by this script.
    response = admin.call(f"/api/users/?q={email}")
    if response["total"]:
        write(admin, "DELETE", path, {"confirm_email": email})
    admin.call("/api/logout/", {})
