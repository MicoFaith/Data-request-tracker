from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.utils import timezone


class User(AbstractUser):
    email_notifications = models.BooleanField(default=False)

    class Role(models.TextChoices):
        CLIENT = "client", "Client"
        OPERATOR = "operator", "Operator"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.CLIENT)
    display_name = models.CharField(max_length=120)
    organisation = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=["client", "operator", "admin"]),
                name="user_valid_role",
            )
        ]


ROBOTS = ["arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"]


class Episode(models.Model):
    episode_id = models.CharField(max_length=40, primary_key=True)
    robot_id = models.CharField(max_length=20)
    task_name = models.CharField(max_length=160)
    recorded_at = models.DateTimeField()
    duration_seconds = models.PositiveIntegerField()
    operator_name = models.CharField(max_length=120)
    quality = models.CharField(
        max_length=6, choices=[("good", "Good"), ("usable", "Usable"), ("bad", "Bad")]
    )

    class Meta:
        ordering = ["episode_id"]
        indexes = [
            models.Index(fields=["recorded_at", "robot_id"], name="episode_date_robot"),
            models.Index(
                fields=["quality", "recorded_at", "task_name"],
                name="episode_quality_date",
            ),
            models.Index(
                fields=["task_name", "quality", "episode_id"],
                name="episode_task_quality",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quality__in=["good", "usable", "bad"]),
                name="episode_valid_quality",
            ),
            models.CheckConstraint(
                condition=Q(robot_id__in=ROBOTS), name="episode_known_robot"
            ),
            models.CheckConstraint(
                condition=Q(duration_seconds__gte=1, duration_seconds__lte=3600),
                name="episode_duration_range",
            ),
        ]


class DatasetRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        IN_PROGRESS = "in_progress", "In progress"
        DELIVERED = "delivered", "Delivered"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    client = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="dataset_requests", db_index=False
    )
    task_name = models.CharField(max_length=160)
    episodes_requested = models.PositiveIntegerField()
    deadline = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.SUBMITTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    first_delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["client", "created_at"], name="request_client_created"
            ),
            models.Index(
                fields=["created_at", "status"], name="request_created_status"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(episodes_requested__gte=1), name="request_positive_count"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "submitted",
                        "in_progress",
                        "delivered",
                        "accepted",
                        "rejected",
                    ]
                ),
                name="request_valid_status",
            ),
        ]


class Assignment(models.Model):
    episode = models.OneToOneField(
        Episode, on_delete=models.PROTECT, related_name="assignment"
    )
    request = models.ForeignKey(
        DatasetRequest, on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_by = models.ForeignKey(User, on_delete=models.PROTECT)
    assigned_at = models.DateTimeField(auto_now_add=True)


class StatusEvent(models.Model):
    request = models.ForeignKey(
        DatasetRequest, on_delete=models.PROTECT, related_name="events"
    )
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "pk"]


class DemoSeedState(models.Model):
    """Remember initial demo setup so deliberately deleted accounts stay deleted."""

    key = models.CharField(max_length=40, primary_key=True)
    completed_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    scope = models.CharField(max_length=10)  # personal, request, staff, admin
    request = models.ForeignKey(DatasetRequest, null=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True)
    email_to = models.EmailField(blank=True)
    email_state = models.CharField(max_length=10, default="off")
    email_attempts = models.PositiveSmallIntegerField(default=0)
    email_due = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["recipient", "read_at", "-created_at"],
                name="notification_inbox",
            ),
            models.Index(
                fields=["email_state", "email_due"], name="notification_outbox"
            ),
        ]
