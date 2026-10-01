import io
import json

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from .models import User, StatusEvent
from .tests import FAST_HASHERS, TEST_STORAGES, accounts, request_for, episode
from .services import assign_episode, transition


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class UserManagementTests(TestCase):
    def setUp(self):
        self.users = accounts()
        self.client.force_login(self.users["admin"])

    def patch(self, user, body):
        return self.client.patch(
            f"/api/users/{user.pk}/", json.dumps(body), content_type="application/json"
        )

    def delete(self, user, email=None):
        return self.client.delete(
            f"/api/users/{user.pk}/",
            json.dumps({"confirm_email": email if email is not None else user.email}),
            content_type="application/json",
        )

    def test_rename_preserves_login_and_can_update_own_name(self):
        user = self.users["client"]
        response = self.patch(user, {"name": "  Aline Uwase  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["name"], "Aline Uwase")
        user.refresh_from_db()
        self.assertEqual(user.username, "a@example.com")
        self.assertTrue(user.check_password("test-password"))
        self.assertEqual(
            self.patch(self.users["admin"], {"name": "Admin Name"}).status_code, 200
        )

    def test_invalid_names_leave_account_unchanged(self):
        user = self.users["client"]
        for name in ["", "   ", "x" * 121, 123, None, []]:
            with self.subTest(name=name):
                response = self.patch(user, {"name": name, "is_active": False})
                self.assertEqual(response.status_code, 422)
                self.assertIn("name", response.json()["error"])
                user.refresh_from_db()
                self.assertEqual(user.display_name, "client")
                self.assertTrue(user.is_active)

    def test_only_admin_may_edit_or_delete_users(self):
        for role in ["client", "operator"]:
            self.client.force_login(self.users[role])
            self.assertEqual(
                self.patch(self.users["other"], {"name": "Changed"}).status_code, 403
            )
            self.assertEqual(self.delete(self.users["other"]).status_code, 403)

    def test_delete_confirmation_and_self_protection(self):
        self.assertEqual(
            self.delete(self.users["other"], "wrong@example.com").status_code, 422
        )
        self.assertEqual(self.delete(self.users["admin"]).status_code, 422)
        self.assertTrue(User.objects.filter(pk=self.users["other"].pk).exists())

    def test_delete_unused_account_revokes_existing_session(self):
        other = Client()
        other.force_login(self.users["other"])
        self.assertEqual(self.delete(self.users["other"]).status_code, 200)
        self.assertFalse(User.objects.filter(pk=self.users["other"].pk).exists())
        self.assertEqual(other.get("/api/me/").status_code, 401)
        self.assertEqual(self.delete(self.users["other"]).status_code, 404)

    def test_request_and_audit_actors_cannot_be_deleted(self):
        obj = request_for(self.users["client"])
        transition(self.users["operator"], obj.pk, "in_progress")
        assign_episode(self.users["operator"], obj.pk, episode().pk)
        for role in ["client", "operator"]:
            response = self.delete(self.users[role])
            self.assertEqual(response.status_code, 409)
            self.assertIn("Deactivate", response.json()["error"])
            self.assertTrue(User.objects.filter(pk=self.users[role].pk).exists())
        self.assertEqual(StatusEvent.objects.filter(request=obj).count(), 2)

    def test_html_name_edit_and_delete_use_same_rules(self):
        user = self.users["other"]
        response = self.client.post(
            "/users/",
            {
                "user_id": user.pk,
                "name": "New name",
                "role": "client",
                "is_active": "true",
            },
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "New name")
        invalid = self.client.post(
            "/users/",
            {
                "user_id": user.pk,
                "name": "Unsaved name",
                "email": "invalid-email",
                "role": "client",
                "is_active": "true",
            },
        )
        self.assertContains(invalid, 'value="invalid-email"')
        self.assertContains(invalid, "Email: Enter a valid email address.")
        user.refresh_from_db()
        self.assertEqual(user.email, "b@example.com")
        self.assertEqual(
            self.client.post(
                "/users/",
                {"user_id": user.pk, "action": "delete", "confirm_email": user.email},
            ).status_code,
            302,
        )
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_delete_requires_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.users["admin"])
        self.assertEqual(
            strict.delete(
                f'/api/users/{self.users["other"].pk}/',
                "{}",
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_startup_seed_does_not_restore_deleted_accounts(self):
        call_command("seed_demo", once=True, skip_episodes=True, stdout=io.StringIO())
        demo = User.objects.get(email="client-a@example.com")
        self.assertEqual(self.delete(demo).status_code, 200)
        call_command("seed_demo", once=True, skip_episodes=True, stdout=io.StringIO())
        self.assertFalse(User.objects.filter(email=demo.email).exists())

    def test_email_and_organisation_update_login_without_changing_password(self):
        user = self.users["client"]
        result = self.patch(
            user,
            {
                "email": "  UPDATED@Example.com  ",
                "organisation": "  New company  ",
                "name": "Updated Person",
            },
        )
        self.assertEqual(result.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.email, "updated@example.com")
        self.assertEqual(user.username, user.email)
        self.assertEqual(user.organisation, "New company")
        auth = Client()
        self.assertFalse(auth.login(username="a@example.com", password="test-password"))
        self.assertTrue(
            auth.login(username="updated@example.com", password="test-password")
        )

    def test_duplicate_email_rejects_whole_update(self):
        user = self.users["client"]
        result = self.patch(
            user,
            {"email": "B@EXAMPLE.COM", "name": "Unwanted change", "is_active": False},
        )
        self.assertEqual(result.status_code, 409)
        self.assertIn("email", result.json()["error"])
        user.refresh_from_db()
        self.assertEqual(user.email, "a@example.com")
        self.assertEqual(user.display_name, "client")
        self.assertTrue(user.is_active)

    def test_invalid_profile_fields_and_clearing_optional_organisation(self):
        user = self.users["client"]
        for payload in [
            {"email": "invalid"},
            {"email": ""},
            {"email": False},
            {"email": "a" * 140 + "@example.com"},
            {"organisation": "x" * 121},
            {"organisation": []},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.patch(user, payload).status_code, 422)
        self.assertEqual(self.patch(user, {"organisation": ""}).status_code, 200)

    def test_email_change_keeps_audit_owner_and_is_not_reseeded(self):
        call_command("seed_demo", once=True, skip_episodes=True, stdout=io.StringIO())
        user = User.objects.get(email="client-a@example.com")
        obj = request_for(user)
        self.assertEqual(
            self.patch(user, {"email": "renamed-client@example.com"}).status_code, 200
        )
        call_command("seed_demo", once=True, skip_episodes=True, stdout=io.StringIO())
        self.assertFalse(User.objects.filter(email="client-a@example.com").exists())
        obj.refresh_from_db()
        self.assertEqual(obj.client_id, user.pk)
        self.assertEqual(obj.events.first().actor_id, user.pk)
