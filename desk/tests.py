import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from datetime import timezone as utc
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .analytics import analytics
from .forms import RequestForm, kigali_today
from .importer import COLUMNS, import_episodes
from .models import Assignment, DatasetRequest, Episode, StatusEvent, User
from .services import (
    DomainError,
    assign_episode,
    create_request,
    transition,
    unassign_episode,
)

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def accounts():
    return {
        role: User.objects.create_user(
            username=email,
            email=email,
            password="test-password",
            role=role if role != "other" else "client",
            display_name=role,
        )
        for role, email in [
            ("client", "a@example.com"),
            ("other", "b@example.com"),
            ("operator", "ops@example.com"),
            ("admin", "admin@example.com"),
        ]
    }


def episode(eid="EP-1", quality="good", task="pick cup", recorded=None):
    return Episode.objects.create(
        episode_id=eid,
        robot_id="arm-01",
        task_name=task,
        recorded_at=recorded or timezone.now(),
        duration_seconds=30,
        operator_name="Aline",
        quality=quality,
    )


def request_for(user, count=1):
    return create_request(
        user,
        {
            "task_name": "pick cup",
            "episodes_requested": count,
            "deadline": kigali_today() + timedelta(days=7),
            "notes": "",
        },
    )


def csv_file(rows):
    import csv

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    stream.seek(0)
    return stream


def row(eid="EP-1", **changes):
    values = dict(
        zip(
            COLUMNS,
            [eid, "arm-01", "pick cup", "2026-08-14T09:12:00", "30", "Aline", "good"],
        )
    )
    values.update(changes)
    return [values[c] for c in COLUMNS]


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class AccessTests(TestCase):
    def setUp(self):
        self.users = accounts()
        self.req = request_for(self.users["client"])
        self.api = Client()

    def auth(self, role):
        self.api.force_login(self.users[role])

    def send(self, path, data, method="post"):
        return getattr(self.api, method)(
            path, json.dumps(data), content_type="application/json"
        )

    def test_login_and_password_hash(self):
        self.assertNotEqual(self.users["client"].password, "test-password")
        self.assertTrue(self.users["client"].check_password("test-password"))
        r = self.send(
            "/api/login/", {"email": " A@example.com ", "password": "test-password"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("password", r.json()["user"])
        self.assertEqual(self.api.get("/api/me/").status_code, 200)

    def test_invalid_login_and_inactive_login(self):
        self.assertEqual(
            self.send(
                "/api/login/", {"email": "a@example.com", "password": "wrong"}
            ).status_code,
            401,
        )
        u = self.users["client"]
        u.is_active = False
        u.save()
        self.assertEqual(
            self.send(
                "/api/login/", {"email": u.email, "password": "test-password"}
            ).status_code,
            401,
        )

    def test_protected_endpoints_and_health(self):
        for url in [
            "/api/me/",
            "/api/requests/",
            "/api/episodes/",
            "/api/users/",
            "/api/analytics/?start=2026-08-01&end=2026-09-30",
            "/health",
        ]:
            self.assertEqual(self.api.get(url).status_code, 401, url)
        self.auth("client")
        self.assertEqual(self.api.get("/health").json()["database"], "ok")

    def test_client_isolation_list_and_direct_id(self):
        self.auth("other")
        self.assertEqual(self.api.get("/api/requests/").json()["total"], 0)
        self.assertEqual(self.api.get(f"/api/requests/{self.req.pk}/").status_code, 404)
        self.assertEqual(
            self.send(
                f"/api/requests/{self.req.pk}/status/", {"status": "accepted"}
            ).status_code,
            404,
        )
        self.assertEqual(self.api.get(f"/requests/{self.req.pk}/").status_code, 404)

    def test_request_creation_ownership_and_input(self):
        self.auth("client")
        values = {
            "task_name": "  PICK   CUP ",
            "episodes_requested": 2,
            "deadline": (kigali_today() + timedelta(days=7)).isoformat(),
        }
        r = self.send("/api/requests/", values)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["request"]["client_id"], self.users["client"].pk)
        self.assertEqual(r.json()["request"]["task_name"], "pick cup")
        for invalid in [
            dict(values, client_id=self.users["other"].pk),
            dict(values, episodes_requested=0),
            dict(values, episodes_requested=True),
            dict(values, deadline="bad"),
            dict(values, task_name=17),
            dict(values, notes=[]),
        ]:
            self.assertEqual(
                self.send("/api/requests/", invalid).status_code, 422, invalid
            )

    def test_client_denied_operator_actions(self):
        self.auth("client")
        for path, data in [
            (f"/api/requests/{self.req.pk}/status/", {"status": "in_progress"}),
            (f"/api/requests/{self.req.pk}/assignments/", {"episode_id": "EP-1"}),
            (
                "/api/users/",
                {
                    "email": "x@example.com",
                    "role": "client",
                    "name": "X",
                    "password": "long-password",
                },
            ),
        ]:
            self.assertEqual(self.send(path, data).status_code, 403)
        self.assertEqual(self.api.get("/api/episodes/").status_code, 403)
        self.assertEqual(self.api.post("/api/episodes/import/").status_code, 403)
        self.assertEqual(
            self.api.get("/api/analytics/?start=2026-08-01&end=2026-09-30").status_code,
            403,
        )

    def test_operator_admin_inherit_fulfilment_not_client_creation(self):
        for role in ["operator", "admin"]:
            self.auth(role)
            self.assertEqual(self.api.get("/api/requests/").json()["total"], 1)
            self.assertEqual(self.api.get("/api/episodes/").status_code, 200)
            self.assertEqual(
                self.send(
                    "/api/requests/",
                    {
                        "task_name": "x",
                        "episodes_requested": 1,
                        "deadline": (kigali_today() + timedelta(days=7)).isoformat(),
                    },
                ).status_code,
                403,
            )
        self.auth("operator")
        self.assertEqual(self.api.get("/api/users/").status_code, 403)

    def test_admin_create_change_deactivate(self):
        self.auth("admin")
        r = self.send(
            "/api/users/",
            {
                "email": "NEW@example.com",
                "name": "New",
                "role": "client",
                "password": "long-password",
            },
        )
        self.assertEqual(r.status_code, 201)
        pk = r.json()["user"]["id"]
        u = User.objects.get(pk=pk)
        self.assertTrue(u.check_password("long-password"))
        self.assertEqual(u.email, "new@example.com")
        self.assertEqual(
            self.send(f"/api/users/{pk}/", {"role": "operator"}, "patch").status_code,
            200,
        )
        self.assertEqual(
            self.send(f"/api/users/{pk}/", {"is_active": "false"}, "patch").status_code,
            422,
        )
        self.assertEqual(
            self.send(f"/api/users/{pk}/", {"is_active": False}, "patch").status_code,
            200,
        )
        self.assertEqual(
            self.send(
                f"/api/users/{self.users['admin'].pk}/", {"is_active": False}, "patch"
            ).status_code,
            422,
        )

    def test_session_observes_deactivation_and_role_changes(self):
        other = Client()
        other.force_login(self.users["operator"])
        self.auth("admin")
        self.send(
            f"/api/users/{self.users['operator'].pk}/", {"role": "client"}, "patch"
        )
        self.assertEqual(other.get("/api/episodes/").status_code, 403)
        self.send(
            f"/api/users/{self.users['operator'].pk}/", {"is_active": False}, "patch"
        )
        self.assertEqual(other.get("/api/me/").status_code, 401)

    def test_csrf_login_and_write(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post(
                "/api/login/",
                {"email": "a@example.com", "password": "test-password"},
                content_type="application/json",
            ).status_code,
            403,
        )
        client.get("/login/")
        token = client.cookies["csrftoken"].value
        r = client.post(
            "/api/login/",
            json.dumps({"email": "a@example.com", "password": "test-password"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            client.post(
                "/api/requests/",
                json.dumps(
                    {
                        "task_name": "pick cup",
                        "episodes_requested": 1,
                        "deadline": (kigali_today() + timedelta(days=7)).isoformat(),
                    }
                ),
                content_type="application/json",
            ).status_code,
            403,
        )
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(
                "/api/requests/",
                json.dumps(
                    {
                        "task_name": "pick cup",
                        "episodes_requested": 1,
                        "deadline": (kigali_today() + timedelta(days=7)).isoformat(),
                    }
                ),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
            ).status_code,
            201,
        )

    def test_malformed_json_methods_and_page(self):
        self.auth("client")
        self.assertEqual(
            self.api.post(
                "/api/requests/", "{", content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(self.api.put("/api/requests/").status_code, 405)
        self.assertEqual(self.api.get("/api/requests/?page=no").status_code, 422)
        self.assertEqual(self.send("/api/requests/", []).status_code, 400)

    def test_paginated_listing(self):
        for _ in range(51):
            request_for(self.users["client"])
        self.auth("client")
        r = self.api.get("/api/requests/").json()
        self.assertEqual(len(r["requests"]), 50)
        self.assertTrue(r["has_next"])
        self.assertEqual(
            len(self.api.get("/api/requests/?page=2").json()["requests"]), 2
        )

    def test_structured_logs(self):
        self.auth("operator")
        with self.assertLogs("desk.requests", level="INFO") as captured:
            self.api.get("/health")
        self.assertEqual(len(captured.records), 1)
        entry = json.loads(captured.records[0].getMessage())
        self.assertEqual(entry["user_id"], self.users["operator"].pk)
        self.assertEqual(
            set(entry), {"method", "path", "status", "duration_ms", "user_id"}
        )
        self.assertGreaterEqual(entry["duration_ms"], 0)
        with self.assertLogs("desk.requests", level="INFO") as captured:
            self.api.get("/api/users/")
        self.assertEqual(json.loads(captured.records[0].getMessage())["status"], 403)

    def test_health_database_failure(self):
        self.auth("client")
        from django.db import OperationalError

        with patch(
            "desk.api.connection.cursor", side_effect=OperationalError("private detail")
        ):
            r = self.api.get("/health")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("private detail", r.content.decode())


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class ValidationTests(TestCase):
    def setUp(self):
        self.u = accounts()
        self.client.force_login(self.u["client"])
        self.values = {
            "task_name": "pick cup",
            "episodes_requested": 2,
            "deadline": (kigali_today() + timedelta(days=7)).isoformat(),
        }

    def post_json(self, path, data):
        return self.client.post(path, json.dumps(data), content_type="application/json")

    def test_deadline_is_future_in_kigali_for_api_html_and_service(self):
        # UTC is still October 3; Kigali has crossed into October 4.
        instant = datetime(2026, 10, 3, 22, 30, tzinfo=utc.utc)
        with patch("django.utils.timezone.now", return_value=instant):
            self.client.force_login(self.u["client"])
            for deadline in ["2026-10-03", "2026-10-04"]:
                values = dict(self.values, deadline=deadline)
                response = self.post_json("/api/requests/", values)
                self.assertEqual(response.status_code, 422)
                self.assertIn("deadline", response.json()["error"])
                response = self.client.post("/requests/new/", values)
                self.assertContains(response, "Deadline must be a future date")
                with self.assertRaises(DomainError):
                    create_request(self.u["client"], values)
            self.assertEqual(DatasetRequest.objects.count(), 0)
            self.assertEqual(StatusEvent.objects.count(), 0)
            response = self.post_json(
                "/api/requests/", dict(self.values, deadline="2026-10-05")
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(StatusEvent.objects.count(), 1)

    def test_deadline_widget_and_stale_form_are_validated_at_submission(self):
        with patch("desk.forms.kigali_today", return_value=date(2026, 10, 4)):
            form = RequestForm(dict(self.values, deadline="2026-10-05"))
            self.assertEqual(form.fields["deadline"].widget.attrs["min"], "2026-10-05")
        with patch("desk.forms.kigali_today", return_value=date(2026, 10, 5)):
            self.assertFalse(form.is_valid())
            self.assertIn("deadline", form.errors)

    def test_invalid_request_values_do_not_create_records(self):
        for changes in [
            {"episodes_requested": 0},
            {"episodes_requested": -1},
            {"episodes_requested": 1000001},
            {"episodes_requested": "1.0"},
            {"episodes_requested": "1e2"},
            {"episodes_requested": True},
            {"task_name": "   "},
            {"task_name": "\u0130" * 160},
            {"notes": "x" * 4001},
            {"deadline": "not-a-date"},
        ]:
            with self.subTest(changes=changes):
                values = dict(self.values, **changes)
                self.assertEqual(
                    self.post_json("/api/requests/", values).status_code, 422
                )
                response = self.client.post("/requests/new/", values)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(DatasetRequest.objects.count(), 0)
        self.assertEqual(StatusEvent.objects.count(), 0)

    def test_empty_html_posts_show_required_errors(self):
        response = self.client.post("/requests/new/", {})
        self.assertContains(response, "This field is required.")
        self.assertTrue(response.context["form"].is_bound)
        self.client.force_login(self.u["admin"])
        response = self.client.post("/users/", {})
        self.assertContains(response, "This field is required.")
        self.assertEqual(User.objects.count(), 4)

    def test_new_password_spaces_are_preserved_and_blank_password_is_rejected(self):
        self.client.force_login(self.u["admin"])
        password = "  a-long-password  "
        for index, path in enumerate(["/api/users/", "/users/"]):
            values = {
                "email": f"space{index}@example.com",
                "name": "Tester",
                "role": "client",
                "password": password,
            }
            response = (
                self.post_json(path, values)
                if index == 0
                else self.client.post(path, values)
            )
            self.assertEqual(response.status_code, 201 if index == 0 else 302)
            user = User.objects.get(email=values["email"])
            self.assertTrue(user.check_password(password))
            self.assertFalse(user.check_password(password.strip()))
            response = self.post_json(
                "/api/login/", {"email": user.email, "password": password}
            )
            self.assertEqual(response.status_code, 200)
            self.client.force_login(self.u["admin"])
        values.update(email="blank@example.com", password=" " * 12)
        self.assertEqual(self.post_json("/api/users/", values).status_code, 422)
        self.assertFalse(User.objects.filter(email="blank@example.com").exists())

    def test_login_email_length_and_duplicate_email(self):
        self.client.force_login(self.u["admin"])
        values = {
            "email": "x" * 60 + "@" + "y" * 60 + "." + "z" * 40 + ".com",
            "name": "Tester",
            "role": "client",
            "password": "long-password",
        }
        response = self.post_json("/api/users/", values)
        self.assertEqual(response.status_code, 422)
        self.assertIn("email", response.json()["error"])
        values["email"] = " A@EXAMPLE.COM "
        self.assertEqual(self.post_json("/api/users/", values).status_code, 409)
        self.assertEqual(User.objects.count(), 4)

    def test_malformed_json_is_rejected_without_server_errors(self):
        for raw in [
            '{"task_name":"a","task_name":"b"}',
            '{"episodes_requested":NaN}',
            '{"episodes_requested":Infinity}',
            '{"episodes_requested":' + "9" * 5000 + "}",
        ]:
            with self.subTest(raw=raw[:50]):
                response = self.client.post(
                    "/api/requests/", raw, content_type="application/json"
                )
                self.assertEqual(response.status_code, 400)
        # Parser depth limits differ by Python build; valid but deeply nested
        # unsupported fields must still fail without an unhandled exception.
        raw = '{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}"
        response = self.client.post(
            "/api/requests/", raw, content_type="application/json"
        )
        self.assertIn(response.status_code, [400, 422])
        self.assertEqual(DatasetRequest.objects.count(), 0)

    def test_unknown_action_fields_and_invalid_episode_ids_do_not_mutate(self):
        req = request_for(self.u["client"])
        episode()
        self.client.force_login(self.u["operator"])
        response = self.post_json(
            f"/api/requests/{req.pk}/status/",
            {"status": "in_progress", "unexpected": True},
        )
        self.assertEqual(response.status_code, 422)
        req.refresh_from_db()
        self.assertEqual(req.status, "submitted")
        self.assertEqual(req.events.count(), 1)
        transition(self.u["operator"], req.pk, "in_progress")
        for fields in [
            {"episode_id": "EP-1", "unexpected": True},
            {"episode_id": ""},
            {"episode_id": "invalid"},
        ]:
            self.assertEqual(
                self.post_json(
                    f"/api/requests/{req.pk}/assignments/", fields
                ).status_code,
                422,
            )
        self.client.post(
            f"/requests/{req.pk}/assign/", {"episode_id": "EP-1", "remove": "wrong"}
        )
        self.assertEqual(req.assignments.count(), 0)

    def test_invalid_active_checkbox_does_not_deactivate_user(self):
        self.client.force_login(self.u["admin"])
        self.client.post(
            "/users/",
            {
                "user_id": self.u["operator"].pk,
                "role": "operator",
                "is_active": "invalid",
            },
        )
        self.u["operator"].refresh_from_db()
        self.assertTrue(self.u["operator"].is_active)

    def test_status_filter_validation_and_results(self):
        first = request_for(self.u["client"])
        second = request_for(self.u["client"])
        transition(self.u["operator"], second.pk, "in_progress")
        self.assertEqual(
            self.client.get("/api/requests/?status=unknown").status_code, 422
        )
        response = self.client.get("/api/requests/?status=submitted")
        self.assertEqual([r["id"] for r in response.json()["requests"]], [first.pk])

    def test_analytics_dates_and_defaults_use_kigali(self):
        self.client.force_login(self.u["operator"])
        for start in ["20260801", "2026-W31-6", "2026-02-30"]:
            self.assertEqual(
                self.client.get(
                    "/api/analytics/", {"start": start, "end": "2026-09-01"}
                ).status_code,
                422,
            )
        instant = datetime(2026, 10, 3, 22, 30, tzinfo=utc.utc)
        with patch("django.utils.timezone.now", return_value=instant):
            self.client.force_login(self.u["operator"])
            response = self.client.get("/analytics/")
            self.assertEqual(response.context["result"]["end"], "2026-10-04")


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class WorkflowTests(TestCase):
    def setUp(self):
        self.u = accounts()
        self.req = request_for(self.u["client"])
        self.ep = episode()

    def start(self):
        return transition(self.u["operator"], self.req.pk, "in_progress")

    def deliver(self):
        self.start()
        assign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        return transition(self.u["operator"], self.req.pk, "delivered")

    def test_accept_and_full_audit(self):
        self.deliver()
        transition(self.u["client"], self.req.pk, "accepted")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "accepted")
        events = list(self.req.events.all())
        self.assertEqual(
            [e.to_status for e in events],
            ["submitted", "in_progress", "delivered", "accepted"],
        )
        self.assertEqual(events[-1].actor_id, self.u["client"].pk)
        self.assertTrue(all(e.at for e in events))

    def test_rework_keeps_first_delivery_and_allows_replacement(self):
        self.deliver()
        self.req.refresh_from_db()
        first = self.req.first_delivered_at
        transition(self.u["client"], self.req.pk, "rejected")
        transition(self.u["admin"], self.req.pk, "in_progress")
        unassign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        ep2 = episode("EP-2", quality="usable")
        assign_episode(self.u["operator"], self.req.pk, ep2.pk)
        transition(self.u["operator"], self.req.pk, "delivered")
        self.req.refresh_from_db()
        self.assertEqual(self.req.first_delivered_at, first)
        self.assertEqual(self.req.assignments.get().episode_id, "EP-2")

    def test_every_disallowed_transition_preserves_audit(self):
        valid = {
            ("submitted", "in_progress"),
            ("in_progress", "delivered"),
            ("rejected", "in_progress"),
            ("delivered", "accepted"),
            ("delivered", "rejected"),
        }
        for source in DatasetRequest.Status.values:
            for target in DatasetRequest.Status.values:
                if (source, target) in valid:
                    continue
                DatasetRequest.objects.filter(pk=self.req.pk).update(status=source)
                before = StatusEvent.objects.count()
                actor = (
                    self.u["client"]
                    if target in ["accepted", "rejected"]
                    else self.u["operator"]
                )
                with self.assertRaises(DomainError):
                    transition(actor, self.req.pk, target)
                self.req.refresh_from_db()
                self.assertEqual(self.req.status, source)
                self.assertEqual(StatusEvent.objects.count(), before)

    def test_wrong_actor_cannot_review(self):
        self.deliver()
        for actor in [self.u["operator"], self.u["admin"], self.u["other"]]:
            with self.assertRaises(DomainError):
                transition(actor, self.req.pk, "accepted")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "delivered")

    def test_status_and_audit_roll_back_together(self):
        with patch(
            "desk.services.StatusEvent.objects.create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.start()
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "submitted")
        self.assertEqual(self.req.events.count(), 1)

    def test_quality_task_and_assignment_state(self):
        with self.assertRaises(DomainError):
            assign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        self.start()
        bad = episode("EP-2", quality="bad")
        mismatch = episode("EP-3", task="open drawer")
        for eid in [bad.pk, mismatch.pk, "EP-404"]:
            with self.assertRaises(DomainError):
                assign_episode(self.u["operator"], self.req.pk, eid)
        assign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        transition(self.u["operator"], self.req.pk, "delivered")
        with self.assertRaises(DomainError):
            unassign_episode(self.u["operator"], self.req.pk, self.ep.pk)

    def test_assignment_uniqueness_and_release(self):
        self.start()
        other = request_for(self.u["other"])
        transition(self.u["operator"], other.pk, "in_progress")
        assign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        with self.assertRaises(DomainError):
            assign_episode(self.u["operator"], other.pk, self.ep.pk)
        unassign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        assign_episode(self.u["operator"], other.pk, self.ep.pk)
        self.assertEqual(Assignment.objects.get().request_id, other.pk)

    def test_database_uniqueness_and_count_constraints(self):
        self.start()
        assign_episode(self.u["operator"], self.req.pk, self.ep.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assignment.objects.create(
                request=self.req, episode=self.ep, assigned_by=self.u["operator"]
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            DatasetRequest.objects.filter(pk=self.req.pk).update(episodes_requested=0)

    def test_delivery_threshold_below_exact_and_above(self):
        for count in [1, 2, 3]:
            req = request_for(self.u["client"], 2)
            transition(self.u["operator"], req.pk, "in_progress")
            for n in range(count):
                assign_episode(self.u["operator"], req.pk, episode(f"EP-{count}{n}").pk)
            if count < 2:
                with self.assertRaises(DomainError):
                    transition(self.u["operator"], req.pk, "delivered")
            else:
                self.assertEqual(
                    transition(self.u["operator"], req.pk, "delivered").status,
                    "delivered",
                )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class ImportTests(TestCase):
    def setUp(self):
        self.u = accounts()

    def test_invalid_utf8_upload_returns_validation_error(self):
        self.client.force_login(self.u["operator"])
        for path, status in [("/api/episodes/import/", 422), ("/episodes/", 200)]:
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    {"file": SimpleUploadedFile("invalid.csv", b"\xffinvalid header")},
                )
                self.assertEqual(response.status_code, status)
                self.assertIn("Invalid UTF-8", response.content.decode())
        self.assertEqual(Episode.objects.count(), 0)

    def test_extreme_dates_and_non_integer_durations_are_skipped(self):
        report = import_episodes(
            self.u["operator"],
            csv_file(
                [
                    row("EP-1", recorded_at="0001-01-01T00:00:00+02:00"),
                    row("EP-2", recorded_at="9999-12-31T23:59:59-02:00"),
                    row("EP-3", duration_seconds="\u00b2"),
                    row("EP-4", duration_seconds="9" * 5000),
                    row("EP-5", duration_seconds="000030"),
                ]
            ),
        )
        self.assertEqual(report["imported"], 1)
        self.assertEqual(
            report["reasons"],
            {"invalid_recorded_at": 2, "duration_outside_1_to_3600": 2},
        )

    def test_normalization_dates_comma_and_quality(self):
        rows = [
            row(
                " ep-1 ", robot_id=" ARM-01 ", task_name=" PICK   CUP ", quality="Good"
            ),
            row("EP-2", recorded_at="14/08/2026 09:15", quality="USABLE"),
            row(
                "EP-3",
                task_name="pick cup, then place",
                recorded_at="2026-08-14 09:12:00",
            ),
        ]
        report = import_episodes(self.u["operator"], csv_file(rows))
        self.assertEqual(report["imported"], 3)
        ep = Episode.objects.get(pk="EP-1")
        self.assertEqual(ep.task_name, "pick cup")
        self.assertEqual(ep.recorded_at.hour, 7)
        self.assertEqual(
            Episode.objects.get(pk="EP-3").task_name, "pick cup, then place"
        )

    def test_bad_rows_report_and_valid_survives(self):
        rows = [
            row(),
            row("EP-2", robot_id="arm-99"),
            row("EP-3", operator_name=""),
            row("EP-4", duration_seconds="N/A"),
            row("EP-5", duration_seconds="999999"),
            row("EP-6", recorded_at="invalid"),
            row("EP-7", quality="excellent"),
            ["EP-8", "arm-01"],
            [],
            ["  "],
        ]
        r = import_episodes(self.u["admin"], csv_file(rows))
        self.assertEqual(r["imported"], 1)
        self.assertEqual(r["skipped"], 9)
        self.assertEqual(r["total_rows"], 10)
        self.assertEqual(sum(r["reasons"].values()), 9)
        self.assertEqual(r["reasons"]["blank_row"], 2)

    def test_idempotency_and_conflicting_case_duplicate_first_wins(self):
        rows = [row(), row("ep-1", task_name="open drawer"), row("EP-2")]
        first = import_episodes(self.u["operator"], csv_file(rows))
        second = import_episodes(self.u["operator"], csv_file(rows))
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["skipped"], 1)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(Episode.objects.count(), 2)
        self.assertEqual(Episode.objects.get(pk="EP-1").task_name, "pick cup")

    def test_supplied_file_totals_and_rerun(self):
        def run():
            with (settings.BASE_DIR / "seed/episodes.csv").open(
                encoding="utf-8-sig", newline=""
            ) as f:
                return import_episodes(self.u["operator"], f)

        first = run()
        second = run()
        self.assertEqual(first["total_rows"], 191)
        self.assertEqual(first["total_rows"], first["imported"] + first["skipped"])
        self.assertEqual(second["imported"], 0)
        self.assertEqual(Episode.objects.count(), first["imported"])
        self.assertIn("wrong_column_count", first["reasons"])

    def test_batches_report_cap_and_no_duplicate_table_scan(self):
        rows = [row(f"EP-{n}") for n in range(600)] + [
            row(f"EP-{n}") for n in range(600)
        ]
        with CaptureQueriesContext(connection) as queries:
            r = import_episodes(self.u["operator"], csv_file(rows))
        self.assertEqual(r["imported"], 600)
        self.assertEqual(r["skipped"], 600)
        self.assertEqual(len(r["rows"]), 200)
        self.assertEqual(r["unlisted_skips"], 400)
        self.assertLess(len(queries), 20)

    def test_header_syntax_and_role(self):
        with self.assertRaises(DomainError):
            import_episodes(self.u["operator"], io.StringIO("wrong,header\n"))
        with self.assertRaises(DomainError):
            import_episodes(self.u["client"], csv_file([row()]))
        malformed = ",".join(COLUMNS) + "\n" + ",".join(row()) + '\n"unfinished'
        with self.assertRaises(DomainError):
            import_episodes(self.u["operator"], io.StringIO(malformed))
        self.assertEqual(Episode.objects.count(), 0)

    def test_import_api_rbac_and_report(self):
        client = Client()
        client.force_login(self.u["operator"])
        source = csv_file([row()]).getvalue().encode()
        r = client.post(
            "/api/episodes/import/",
            {"file": SimpleUploadedFile("test.csv", source, content_type="text/csv")},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported"], 1)
        client.force_login(self.u["client"])
        self.assertEqual(
            client.post(
                "/api/episodes/import/",
                {"file": SimpleUploadedFile("test.csv", source)},
            ).status_code,
            403,
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class AnalyticsAndUITests(TestCase):
    def setUp(self):
        self.u = accounts()

    def test_median_even_odd_and_empty(self):
        start = datetime(2026, 8, 1, 8, tzinfo=utc.utc)
        for duration in [10, 20, 90]:
            req = request_for(self.u["client"])
            DatasetRequest.objects.filter(pk=req.pk).update(
                created_at=start,
                first_delivered_at=start + timedelta(seconds=duration),
                status="accepted",
            )
        self.assertEqual(
            analytics(date(2026, 8, 1), date(2026, 8, 1))["request_fulfilment"][
                "median_seconds_submitted_to_first_delivered"
            ],
            20,
        )
        req = request_for(self.u["client"])
        DatasetRequest.objects.filter(pk=req.pk).update(
            created_at=start, first_delivered_at=start + timedelta(seconds=40)
        )
        self.assertEqual(
            analytics(date(2026, 8, 1), date(2026, 8, 1))["request_fulfilment"][
                "median_seconds_submitted_to_first_delivered"
            ],
            30,
        )
        self.assertIsNone(
            analytics(date(2025, 1, 1), date(2025, 1, 2))["request_fulfilment"][
                "median_seconds_submitted_to_first_delivered"
            ]
        )

    def test_range_kigali_quality_and_db_aggregation(self):
        episode("EP-1", recorded=datetime(2026, 8, 1, 21, 59, tzinfo=utc.utc))
        episode("EP-2", recorded=datetime(2026, 8, 1, 22, 0, tzinfo=utc.utc))
        episode(
            "EP-3", quality="bad", recorded=datetime(2026, 8, 1, 10, tzinfo=utc.utc)
        )
        episode(
            "EP-4", quality="usable", recorded=datetime(2026, 8, 1, 10, tzinfo=utc.utc)
        )
        with CaptureQueriesContext(connection) as captured:
            r = analytics(date(2026, 8, 1), date(2026, 8, 1))
        self.assertEqual(r["episodes_per_day_per_robot"][0]["count"], 3)
        self.assertEqual(r["top_5_good_tasks"], [{"task_name": "pick cup", "count": 1}])
        self.assertEqual(len(captured), 4)
        self.assertTrue(any("GROUP BY" in q["sql"] for q in captured))
        median_function = (
            "PERCENTILE_CONT" if connection.vendor == "postgresql" else "ROW_NUMBER"
        )
        self.assertTrue(any(median_function in q["sql"].upper() for q in captured))

    def test_analytics_date_validation_and_filters(self):
        client = Client()
        client.force_login(self.u["operator"])
        for suffix in [
            "",
            "?start=bad&end=2026-09-01",
            "?start=2026-09-01&end=2026-08-01",
            "?start=0001-01-01&end=2026-09-01",
        ]:
            self.assertEqual(client.get("/api/analytics/" + suffix).status_code, 422)
        episode()
        episode("EP-2", quality="bad")
        r = client.get(
            "/api/episodes/?task_name=PICK%20CUP&quality=good&available=true"
        )
        self.assertEqual(r.json()["total"], 1)
        self.assertEqual(
            client.get("/api/episodes/?quality=excellent").status_code, 422
        )

    def test_client_ui_lifecycle_and_xss_escape(self):
        client = Client()
        client.force_login(self.u["client"])
        r = client.post(
            "/requests/new/",
            {
                "task_name": "pick cup",
                "episodes_requested": 1,
                "deadline": (kigali_today() + timedelta(days=7)).isoformat(),
                "notes": "<script>alert(1)</script>",
            },
        )
        self.assertEqual(r.status_code, 302)
        req = DatasetRequest.objects.get()
        self.assertContains(client.get(r.url), "&lt;script&gt;")
        transition(self.u["operator"], req.pk, "in_progress")
        assign_episode(self.u["operator"], req.pk, episode().pk)
        transition(self.u["operator"], req.pk, "delivered")
        self.assertContains(client.get(r.url), "Accept delivery")
        client.post(f"/requests/{req.pk}/status/", {"status": "accepted"})
        req.refresh_from_db()
        self.assertEqual(req.status, "accepted")

    def test_operator_ui_and_all_templates(self):
        req = request_for(self.u["client"])
        transition(self.u["operator"], req.pk, "in_progress")
        episode()
        client = Client()
        client.force_login(self.u["operator"])
        for url in ["/", "/episodes/", "/analytics/", f"/requests/{req.pk}/"]:
            r = client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, "htmx")
        client.post(f"/requests/{req.pk}/assign/", {"episode_id": "EP-1"})
        self.assertEqual(req.assignments.count(), 1)
        client.post(f"/requests/{req.pk}/status/", {"status": "delivered"})
        req.refresh_from_db()
        self.assertEqual(req.status, "delivered")
        client.force_login(self.u["admin"])
        self.assertEqual(client.get("/users/").status_code, 200)

    def test_seed_users_hashes_and_rerun_preserves_changes(self):
        out = io.StringIO()
        call_command("seed_demo", skip_episodes=True, stdout=out)
        self.assertEqual(
            User.objects.filter(
                email__in=[
                    "admin@example.com",
                    "ops1@example.com",
                    "ops2@example.com",
                    "client-a@example.com",
                    "client-b@example.com",
                ]
            ).count(),
            5,
        )
        u = User.objects.get(email="ops1@example.com")
        self.assertTrue(u.check_password("ops123"))
        u.is_active = False
        u.role = "client"
        u.save()
        call_command("seed_demo", skip_episodes=True, stdout=out)
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        self.assertEqual(u.role, "client")


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class WorkspaceUXTests(TestCase):
    def setUp(self):
        self.u = accounts()
        self.own = request_for(self.u["client"])
        self.other = request_for(self.u["other"])

    def test_dashboard_counts_search_and_overdue_respect_client_scope(self):
        DatasetRequest.objects.filter(pk=self.other.pk).update(
            status="rejected", deadline=kigali_today() - timedelta(days=1)
        )
        self.client.force_login(self.u["client"])
        response = self.client.get("/")
        self.assertEqual(response.context["stats"]["total"], 1)
        self.assertEqual(response.context["stats"]["rejected"], 0)
        self.assertEqual(response.context["stats"]["overdue"], 0)
        response = self.client.get("/", {"q": f"#{self.other.pk}"})
        self.assertEqual(response.context["meta"]["total"], 0)
        self.assertEqual(response.context["stats"]["total"], 1)
        self.client.force_login(self.u["operator"])
        response = self.client.get("/", {"attention": "overdue", "sort": "deadline"})
        self.assertEqual(response.context["stats"]["total"], 2)
        self.assertEqual([r.pk for r in response.context["rows"]], [self.other.pk])

    def test_invalid_filters_remain_editable_on_each_screen(self):
        transition(self.u["operator"], self.own.pk, "in_progress")
        self.client.force_login(self.u["admin"])
        for path, params in [
            ("/", {"status": "invalid"}),
            ("/", {"q": "x" * 161}),
            ("/", {"page": "bad"}),
            ("/episodes/", {"quality": "invalid"}),
            (f"/requests/{self.own.pk}/", {"quality": "invalid"}),
            ("/users/", {"active": "invalid"}),
        ]:
            with self.subTest(path=path, params=params):
                response = self.client.get(path, params)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Check your filters")
                self.assertContains(response, "<form")
                self.assertTrue(response.context["filter_form"].errors)
        response = self.client.get(
            "/analytics/", {"start": "2026-10-04", "end": "2026-10-01"}
        )
        self.assertContains(response, "End date must be on or after the start date.")
        self.assertContains(response, 'value="2026-10-04"')
        self.assertIsNone(response.context["result"])

    def test_request_errors_preserve_values_and_offer_field_links(self):
        self.client.force_login(self.u["client"])
        response = self.client.post(
            "/requests/new/",
            {
                "task_name": "pick cup",
                "episodes_requested": "0",
                "deadline": kigali_today().isoformat(),
                "notes": "Keep these instructions",
            },
        )
        self.assertContains(response, 'id="validation-summary"')
        self.assertContains(response, 'href="#id_deadline"')
        self.assertContains(response, "Keep these instructions")
        self.assertContains(response, 'aria-invalid="true"')
        self.assertEqual(DatasetRequest.objects.count(), 2)

    def test_user_search_duplicate_email_and_protected_own_access(self):
        self.client.force_login(self.u["admin"])
        response = self.client.get(
            "/users/", {"q": "ops@", "role": "operator", "active": "true"}
        )
        self.assertEqual(
            [u.pk for u in response.context["rows"]], [self.u["operator"].pk]
        )
        response = self.client.post(
            "/users/",
            {
                "email": "a@example.com",
                "name": "Name to keep",
                "role": "client",
                "password": "long-password",
            },
        )
        self.assertContains(response, 'href="#id_email"')
        self.assertContains(response, 'value="Name to keep"')
        self.assertContains(response, "Your administrator access is protected")
        self.assertEqual(User.objects.count(), 4)

    def test_assignment_keeps_filters_and_no_external_redirect(self):
        transition(self.u["operator"], self.own.pk, "in_progress")
        episode(quality="usable")
        self.client.force_login(self.u["operator"])
        response = self.client.post(
            f"/requests/{self.own.pk}/assign/?quality=usable&task_name=pick%20cup&page=2",
            {"episode_id": "EP-1", "next": "https://example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"/requests/{self.own.pk}/?quality=usable&task_name=pick+cup#assignment-panel",
        )
        self.assertEqual(self.own.assignments.count(), 1)

    def test_navigation_refresh_and_pagination_keep_query(self):
        self.client.force_login(self.u["operator"])
        response = self.client.get(
            "/episodes/",
            {"task_name": "pick cup", "quality": "usable"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, 'hx-select-oob="#app-header"')
        self.assertContains(
            response, '<a href="/episodes/" aria-current="page">Episodes</a>', html=True
        )
        self.assertEqual(
            response.context["page_query"], "task_name=pick+cup&quality=usable"
        )
        if (settings.BASE_DIR / "static/react/.vite/manifest.json").exists():
            self.assertContains(response, 'type="module"')
            self.assertNotContains(response, "vendor/htmx.min.js")
        else:
            self.assertContains(response, "app.js")


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class ConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_two_simultaneous_assignments_one_winner(self):
        u = accounts()
        r1 = request_for(u["client"])
        r2 = request_for(u["other"])
        ep = episode()
        transition(u["operator"], r1.pk, "in_progress")
        transition(u["operator"], r2.pk, "in_progress")
        barrier = Barrier(2)

        def attempt(pk):
            close_old_connections()
            barrier.wait()
            try:
                assign_episode(u["operator"], pk, ep.pk)
                return "assigned"
            except DomainError:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [r1.pk, r2.pk]))
        self.assertCountEqual(results, ["assigned", "conflict"])
        self.assertEqual(Assignment.objects.count(), 1)
