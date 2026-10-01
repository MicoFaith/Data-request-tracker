import io
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Notification, User
from .notifications import (
    deliver_batch,
    notify,
    set_email_preference,
    visible_notifications,
)
from .services import (
    create_request,
    transition,
    assign_episode,
    unassign_episode,
    change_user,
    create_user,
    delete_user,
    DomainError,
)
from .tests import accounts, episode, FAST_HASHERS, TEST_STORAGES


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, STORAGES=TEST_STORAGES)
class NotificationTests(TestCase):
    def setUp(self):
        self.users = accounts()
        self.owner = self.users["client"]
        self.admin = self.users["admin"]
        self.operator = self.users["operator"]

    def request(self):
        return create_request(
            self.owner,
            {
                "task_name": "pick cup",
                "episodes_requested": 1,
                "deadline": (timezone.localdate() + timedelta(days=5)).isoformat(),
            },
        )

    def login(self, user=None):
        self.client.force_login(user or self.owner)

    def post(self, body):
        return self.client.post(
            "/api/notifications/", body, content_type="application/json"
        )

    def test_new_request_reaches_owner_and_staff_only(self):
        self.request()
        self.assertEqual(
            set(Notification.objects.values_list("recipient_id", flat=True)),
            {self.owner.pk, self.operator.pk, self.admin.pk},
        )
        self.assertFalse(Notification.objects.exclude(email_state="off").exists())

    def test_workflow_and_assignments_notify(self):
        obj = self.request()
        transition(self.operator, obj.pk, "in_progress")
        assign_episode(self.operator, obj.pk, episode().pk)
        unassign_episode(self.operator, obj.pk, "EP-1")
        assign_episode(self.operator, obj.pk, "EP-1")
        transition(self.operator, obj.pk, "delivered")
        transition(self.owner, obj.pk, "accepted")
        self.assertEqual(self.owner.notifications.count(), 7)
        self.assertIn("accepted", self.owner.notifications.first().title)

    def test_failed_actions_do_not_notify(self):
        obj = self.request()
        with self.assertRaises(DomainError):
            transition(self.operator, obj.pk, "delivered")
        self.assertEqual(Notification.objects.count(), 3)

    def test_rollback_removes_notifications_and_outbox(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.request()
                raise RuntimeError("rollback")
        self.assertEqual(Notification.objects.count(), 0)

    def test_admin_account_events_and_unused_deletion(self):
        user = create_user(
            self.admin,
            {
                "name": "New user",
                "email": "new@example.com",
                "password": "safe-password",
                "role": "client",
            },
        )
        self.assertEqual(user.notifications.count(), 1)
        change_user(self.admin, user.pk, {"organisation": "Lab"})
        delete_user(self.admin, user.pk, user.email)
        self.assertEqual(
            list(self.admin.notifications.values_list("title", flat=True)),
            ["User deleted", "User updated", "User created"],
        )
        self.assertFalse(Notification.objects.filter(recipient_id=user.pk).exists())
        self.assertFalse(self.operator.notifications.exists())

    def test_import_summary_is_staff_only(self):
        from .importer import import_episodes, COLUMNS

        import_episodes(self.operator, io.StringIO(",".join(COLUMNS) + "\n"))
        self.assertEqual(Notification.objects.count(), 2)
        self.assertFalse(self.owner.notifications.exists())

    def test_notification_reads_are_scoped_and_idempotent(self):
        self.request()
        own = self.owner.notifications.get()
        self.login()
        self.assertEqual(
            self.client.get("/api/notifications/").json()["unread_count"], 1
        )
        other = self.operator.notifications.get()
        self.assertEqual(self.post({"id": other.pk}).status_code, 404)
        self.assertEqual(self.post({"id": own.pk}).status_code, 200)
        own.refresh_from_db()
        read_at = own.read_at
        self.assertEqual(self.post({"id": own.pk}).status_code, 200)
        own.refresh_from_db()
        self.assertEqual(own.read_at, read_at)
        self.assertEqual(
            self.client.get("/api/notifications/?unread=true").json()["total"], 0
        )
        self.assertEqual(
            self.operator.notifications.filter(read_at__isnull=True).count(), 1
        )

    def test_mark_all_does_not_touch_another_user(self):
        self.request()
        self.login()
        self.assertEqual(self.post({"all": True}).status_code, 200)
        self.assertEqual(
            self.owner.notifications.filter(read_at__isnull=True).count(), 0
        )
        self.assertEqual(
            self.operator.notifications.filter(read_at__isnull=True).count(), 1
        )

    def test_role_downgrade_hides_prior_privileged_activity(self):
        self.request()
        old = self.operator.notifications.get()
        change_user(self.admin, self.operator.pk, {"role": "client"})
        self.operator.refresh_from_db()
        self.assertFalse(
            visible_notifications(self.operator).filter(pk=old.pk).exists()
        )
        self.login(self.operator)
        self.assertEqual(self.post({"id": old.pk}).status_code, 404)
        titles = [
            n["title"]
            for n in self.client.get("/api/notifications/").json()["notifications"]
        ]
        self.assertEqual(titles, ["Your account was updated"])

    def test_invalid_filters_and_read_payloads(self):
        self.login()
        for data in (
            {},
            {"id": True},
            {"id": -1},
            {"all": "true"},
            {"all": True, "id": 1},
            {"recipient": 1},
        ):
            self.assertEqual(self.post(data).status_code, 422)
        for query in ("page=0", "page=oops", "unread=oops"):
            self.assertEqual(
                self.client.get("/api/notifications/?" + query).status_code, 422
            )

    def test_authentication_csrf_and_inactive_denials(self):
        self.assertEqual(self.client.get("/api/notifications/").status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(
            client.post(
                "/api/notifications/", {"all": True}, content_type="application/json"
            ).status_code,
            403,
        )
        self.login()
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.client.get("/api/notifications/").status_code, 401)

    def test_pagination(self):
        Notification.objects.bulk_create(
            [
                Notification(
                    recipient=self.owner,
                    scope="personal",
                    title=str(i),
                    message="Update",
                )
                for i in range(51)
            ]
        )
        self.login()
        first = self.client.get("/api/notifications/").json()
        second = self.client.get("/api/notifications/?page=2").json()
        self.assertEqual(
            (first["total"], len(first["notifications"]), len(second["notifications"])),
            (51, 50, 1),
        )
        self.assertTrue(first["has_next"])

    def test_preferences_validate_boolean_and_disabled_mail(self):
        self.login()
        url = "/api/notifications/preferences/"
        for data in (
            {},
            {"email_notifications": "true"},
            {"email_notifications": 1},
            {"email_notifications": False, "email": "evil@example.com"},
        ):
            self.assertEqual(
                self.client.patch(
                    url, data, content_type="application/json"
                ).status_code,
                422,
            )
        self.assertEqual(
            self.client.patch(
                url, {"email_notifications": True}, content_type="application/json"
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.patch(
                url, {"email_notifications": False}, content_type="application/json"
            ).status_code,
            200,
        )

    def test_notification_page_deep_link(self):
        self.login()
        self.assertEqual(self.client.get("/notifications/").status_code, 200)


@override_settings(
    PASSWORD_HASHERS=FAST_HASHERS,
    NOTIFICATION_EMAIL_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="desk@example.com",
    APP_BASE_URL="https://desk.example.com",
)
class NotificationEmailTests(TestCase):
    def setUp(self):
        self.users = accounts()
        self.owner = self.users["client"]
        set_email_preference(self.owner, True)

    def queue(self):
        notify(
            "Private account activity",
            "Sensitive details stay in the inbox",
            scope="personal",
            recipient=self.owner,
        )
        return self.owner.notifications.first()

    def test_send_once_and_omit_private_details(self):
        item = self.queue()
        self.assertEqual(item.email_state, "pending")
        self.assertEqual(deliver_batch(), 1)
        self.assertEqual(deliver_batch(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.owner.email])
        self.assertIn("https://desk.example.com/notifications/", mail.outbox[0].body)
        self.assertNotIn("Sensitive", mail.outbox[0].body)
        item.refresh_from_db()
        self.assertEqual(item.email_state, "sent")

    def test_failure_retries_without_losing_inbox(self):
        item = self.queue()
        with patch(
            "django.core.mail.EmailMessage.send", side_effect=OSError("unavailable")
        ):
            self.assertEqual(deliver_batch(), 0)
        item.refresh_from_db()
        self.assertEqual((item.email_state, item.email_attempts), ("pending", 1))
        self.assertGreater(item.email_due, timezone.now())
        self.assertEqual(deliver_batch(), 0)
        Notification.objects.filter(pk=item.pk).update(email_due=timezone.now())
        self.assertEqual(deliver_batch(), 1)
        self.assertEqual(self.owner.notifications.count(), 1)

    def test_retry_limit(self):
        item = self.queue()
        Notification.objects.filter(pk=item.pk).update(email_attempts=4)
        with patch(
            "django.core.mail.EmailMessage.send", side_effect=OSError("unavailable")
        ):
            deliver_batch()
        item.refresh_from_db()
        self.assertEqual((item.email_state, item.email_attempts), ("failed", 5))
        self.assertEqual(deliver_batch(), 0)

    def test_crashed_worker_lease_recovers(self):
        item = self.queue()
        Notification.objects.filter(pk=item.pk).update(
            email_state="sending", email_due=timezone.now() + timedelta(minutes=1)
        )
        self.assertEqual(deliver_batch(), 0)
        Notification.objects.filter(pk=item.pk).update(
            email_due=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(deliver_batch(), 1)

    def test_opt_out_cancels_pending_and_future_mail(self):
        item = self.queue()
        set_email_preference(self.owner, False)
        item.refresh_from_db()
        self.assertEqual(item.email_state, "cancelled")
        self.assertEqual(self.queue().email_state, "off")
        self.assertEqual(deliver_batch(), 0)

    def test_email_change_resets_preference_and_cancels_old_destination(self):
        item = self.queue()
        change_user(
            self.users["admin"], self.owner.pk, {"email": "changed@example.com"}
        )
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.email_notifications)
        self.assertEqual(deliver_batch(), 0)
        item.refresh_from_db()
        self.assertEqual(item.email_state, "cancelled")

    def test_inactive_recipient_is_skipped(self):
        item = self.queue()
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(deliver_batch(), 0)
        item.refresh_from_db()
        self.assertEqual(item.email_state, "cancelled")

    def test_former_admin_cannot_receive_queued_admin_activity(self):
        admin = self.users["admin"]
        set_email_preference(admin, True)
        notify("User created", "Private", scope="admin")
        User.objects.filter(pk=admin.pk).update(role="client")
        self.assertEqual(deliver_batch(), 0)
        self.assertEqual(admin.notifications.get().email_state, "cancelled")

    def test_preference_is_only_for_authenticated_account(self):
        self.client.force_login(self.owner)
        response = self.client.patch(
            "/api/notifications/preferences/",
            {"email_notifications": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["email_notifications"])
        self.assertFalse(self.users["other"].email_notifications)

    @override_settings(NOTIFICATION_EMAIL_RECIPIENTS=["approved@example.com"])
    def test_demo_recipient_allowlist_applies_to_queue_and_opt_in(self):
        self.assertEqual(self.queue().email_state, "off")
        self.client.force_login(self.owner)
        response = self.client.patch(
            "/api/notifications/preferences/",
            {"email_notifications": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_removed_allowlist_recipient_is_cancelled_before_send(self):
        item = self.queue()
        with override_settings(NOTIFICATION_EMAIL_RECIPIENTS=["approved@example.com"]):
            self.assertEqual(deliver_batch(), 0)
        item.refresh_from_db()
        self.assertEqual(item.email_state, "cancelled")
