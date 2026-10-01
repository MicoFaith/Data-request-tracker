from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import DatasetRequest
from .tests import FAST_HASHERS, TEST_STORAGES, accounts, episode, request_for


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class ReactAPITests(TestCase):
    def setUp(self):
        self.users = accounts()
        self.a = request_for(self.users["client"])
        self.b = request_for(self.users["other"])

    def test_public_session_exposes_no_private_data_and_sets_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get("/api/session/")
        self.assertIsNone(response.json()["user"])
        self.assertIn("csrftoken", response.cookies)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(
            response.json()["tomorrow"],
            (timezone.localdate() + timedelta(days=1)).isoformat(),
        )
        denied = client.post(
            "/api/login/",
            {"email": "a@example.com", "password": "test-password"},
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)
        allowed = client.post(
            "/api/login/",
            {"email": "a@example.com", "password": "test-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=response.cookies["csrftoken"].value,
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(client.get("/api/session/").json()["user"]["role"], "client")

    def test_dashboard_scopes_client_counts_and_staff_only_summaries(self):
        self.client.force_login(self.users["client"])
        data = self.client.get("/api/dashboard/").json()
        self.assertEqual(data["counts"]["total"], 1)
        self.assertNotIn("inventory", data)
        self.assertNotIn("people", data)
        self.client.force_login(self.users["operator"])
        data = self.client.get("/api/dashboard/").json()
        self.assertEqual(data["counts"]["total"], 2)
        self.assertIn("inventory", data)
        self.assertNotIn("people", data)
        self.client.force_login(self.users["admin"])
        self.assertEqual(
            self.client.get("/api/dashboard/").json()["people"]["active"], 4
        )

    def test_request_search_does_not_bypass_ownership(self):
        self.client.force_login(self.users["client"])
        self.assertEqual(
            self.client.get("/api/requests/", {"q": f"#{self.b.pk}"}).json()["total"], 0
        )
        self.assertEqual(
            self.client.get("/api/requests/", {"q": "pick cup"}).json()["total"], 1
        )
        self.assertEqual(
            self.client.get("/api/requests/", {"sort": "invalid"}).status_code, 422
        )
        self.assertEqual(
            self.client.get("/api/requests/", {"q": "x" * 161}).status_code, 422
        )

    def test_overdue_filter_and_human_readable_detail(self):
        DatasetRequest.objects.filter(pk=self.a.pk).update(
            deadline=timezone.localdate() - timedelta(days=1)
        )
        self.client.force_login(self.users["operator"])
        data = self.client.get("/api/requests/", {"attention": "overdue"}).json()
        self.assertEqual([r["id"] for r in data["requests"]], [self.a.pk])
        detail = self.client.get(f"/api/requests/{self.a.pk}/").json()
        self.assertEqual(detail["request"]["client_name"], "client")
        self.assertEqual(detail["history"][0]["actor_name"], "client")

    def test_user_filters_are_admin_only_and_validated(self):
        self.client.force_login(self.users["operator"])
        self.assertEqual(
            self.client.get("/api/users/", {"q": "client"}).status_code, 403
        )
        self.client.force_login(self.users["admin"])
        self.assertEqual(
            self.client.get("/api/users/", {"role": "client", "active": "true"}).json()[
                "total"
            ],
            2,
        )
        self.assertEqual(
            self.client.get("/api/users/", {"role": "root"}).status_code, 422
        )
        self.assertEqual(
            self.client.get("/api/users/", {"active": "maybe"}).status_code, 422
        )
