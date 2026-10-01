"""Transactional activity inbox and a durable, opt-in SMTP outbox."""

from datetime import timedelta
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Notification, User


def email_available(user):
    return settings.NOTIFICATION_EMAIL_ENABLED and (
        not settings.NOTIFICATION_EMAIL_RECIPIENTS
        or user.email.lower() in settings.NOTIFICATION_EMAIL_RECIPIENTS
    )


def visible_notifications(user):
    scope = Q(scope="personal") | Q(scope="request", request__client=user)
    if user.role in ("operator", "admin"):
        scope |= Q(scope__in=["request", "staff"])
    if user.role == "admin":
        scope |= Q(scope="admin")
    return Notification.objects.filter(recipient=user).filter(scope)


def notify(title, message, *, request=None, scope="staff", recipient=None):
    users = User.objects.filter(is_active=True)
    if recipient is not None:
        users = users.filter(pk=recipient.pk)
    elif request is not None:
        users = users.filter(
            Q(pk=request.client_id) | Q(role__in=["admin", "operator"])
        )
        scope = "request"
    else:
        users = (
            users.filter(role="admin")
            if scope == "admin"
            else users.filter(role__in=["admin", "operator"])
        )
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=user,
                scope=scope,
                request=request,
                title=title,
                message=message,
                email_to=(
                    user.email
                    if user.email_notifications and email_available(user)
                    else ""
                ),
                email_state=(
                    "pending"
                    if user.email_notifications and email_available(user)
                    else "off"
                ),
            )
            for user in users
        ]
    )


def notification_path(item):
    if item.scope == "request" and item.request_id:
        return f"/requests/{item.request_id}/"
    return {"admin": "/users/", "staff": "/episodes/"}.get(
        item.scope, "/notifications/"
    )


def set_email_preference(user, enabled):
    # Serialize preference changes with event creation and outbox claiming on SQLite.
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(email_notifications=enabled)
        if not enabled:
            Notification.objects.filter(
                recipient=user, email_state__in=["pending", "sending"]
            ).update(email_state="cancelled")


def deliver_batch(limit=50):
    """Claim outside network I/O; a ten-minute lease recovers interrupted workers.

    SMTP acceptance is not proof of inbox delivery. A crash after acceptance can
    cause a duplicate on retry; stable Message-ID helps providers deduplicate.
    """
    if not settings.NOTIFICATION_EMAIL_ENABLED:
        return 0
    sent = 0
    for _ in range(limit):
        with transaction.atomic():
            item = (
                Notification.objects.select_for_update()
                .filter(
                    email_state__in=["pending", "sending"],
                    email_due__lte=timezone.now(),
                )
                .order_by("email_due", "pk")
                .first()
            )
            if item is None:
                break
            user = User.objects.get(pk=item.recipient_id)
            if (
                not user.is_active
                or not user.email_notifications
                or not email_available(user)
                or user.email != item.email_to
                or not visible_notifications(user).filter(pk=item.pk).exists()
            ):
                item.email_state = "cancelled"
                item.save(update_fields=["email_state"])
                continue
            if item.email_attempts >= 5:
                item.email_state = "failed"
                item.save(update_fields=["email_state"])
                continue
            item.email_attempts += 1
            item.email_state = "sending"
            item.email_due = timezone.now() + timedelta(minutes=10)
            item.save(update_fields=["email_attempts", "email_state", "email_due"])
        try:
            # Keep mail generic: privileged activity details are available only
            # after login, even if access changes while a send is in flight.
            from django.core.mail import EmailMessage

            mail = EmailMessage(
                "New activity in Dataset Request Desk",
                "There is new activity in your workspace. Sign in to view your notifications:\n"
                + settings.APP_BASE_URL.rstrip("/")
                + "/notifications/\n\n"
                + "Manage email updates on the Notifications page.",
                settings.DEFAULT_FROM_EMAIL,
                [item.email_to],
                headers={
                    "Message-ID": f"<desk-notification-{item.pk}@{settings.DEFAULT_FROM_EMAIL.split('@')[-1]}>"
                },
            )
            if mail.send() != 1:
                raise RuntimeError("Mail backend did not accept the message")
        except Exception:
            # Never log SMTP credentials, recipient addresses or provider responses.
            logging.getLogger(__name__).warning(
                "notification_email_failed id=%s attempt=%s",
                item.pk,
                item.email_attempts,
            )
            Notification.objects.filter(
                pk=item.pk, email_state="sending", email_attempts=item.email_attempts
            ).update(
                email_state="failed" if item.email_attempts >= 5 else "pending",
                email_due=timezone.now() + timedelta(minutes=2**item.email_attempts),
            )
        else:
            Notification.objects.filter(
                pk=item.pk, email_state="sending", email_attempts=item.email_attempts
            ).update(email_state="sent")
            sent += 1
    return sent
