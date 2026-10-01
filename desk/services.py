import re

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django import forms
from django.utils import timezone

from .forms import RequestForm, normalize_task
from .models import Assignment, DatasetRequest, Episode, StatusEvent, User
from .notifications import notify
from .locking import serialize_mutation


class DomainError(Exception):
    def __init__(self, message, status=422):
        self.message, self.status = message, status


def episode_key(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"EP-\d{1,30}", value.strip().upper()
    ):
        raise DomainError("Provide a valid episode ID, for example EP-00001.")
    return value.strip().upper()


def require_role(actor, *roles):
    if not actor.is_authenticated or not actor.is_active:
        raise DomainError("Login required.", 401)
    if actor.role not in roles:
        raise DomainError("This role cannot perform that action.", 403)


def visible_requests(actor):
    require_role(actor, *User.Role.values)
    query = DatasetRequest.objects.select_related("client").annotate(
        assigned_count=Count("assignments")
    )
    return query.filter(client=actor) if actor.role == "client" else query


def get_request(actor, pk, locked=False):
    require_role(actor, *User.Role.values)
    query = DatasetRequest.objects
    if actor.role == "client":
        query = query.filter(client=actor)
    if locked:
        query = query.select_for_update()
    try:
        return query.get(pk=pk)
    except DatasetRequest.DoesNotExist:
        raise DomainError("Request not found.", 404)


@transaction.atomic
def create_request(actor, values):
    require_role(actor, "client")
    form = RequestForm(values)
    if not form.is_valid():
        raise DomainError(dict(form.errors))
    obj = DatasetRequest.objects.create(client=actor, **form.cleaned_data)
    StatusEvent.objects.create(
        request=obj, from_status="", to_status="submitted", actor=actor
    )
    notify(
        f"Request #{obj.pk} submitted",
        "A new dataset request is ready for review.",
        request=obj,
    )
    return obj


@transaction.atomic
def transition(actor, pk, target):
    obj = get_request(actor, pk, locked=True)
    if target in ["accepted", "rejected"]:
        require_role(actor, "client")
        allowed = obj.status == "delivered"
    else:
        require_role(actor, "operator", "admin")
        allowed = (obj.status, target) in [
            ("submitted", "in_progress"),
            ("in_progress", "delivered"),
            ("rejected", "in_progress"),
        ]
    if not allowed:
        raise DomainError(f"Cannot move {obj.status} to {target}.", 409)
    if target == "delivered" and obj.assignments.count() < obj.episodes_requested:
        raise DomainError(
            "Assign the requested number of episodes before delivery.", 409
        )
    previous = obj.status
    obj.status = target
    if target == "delivered" and obj.first_delivered_at is None:
        obj.first_delivered_at = timezone.now()
    obj.save(update_fields=["status", "first_delivered_at"])
    StatusEvent.objects.create(
        request=obj, from_status=previous, to_status=target, actor=actor
    )
    notify(
        f"Request #{obj.pk}: {target.replace('_', ' ')}",
        f"Status changed from {previous.replace('_', ' ')} to {target.replace('_', ' ')}.",
        request=obj,
    )
    return obj


@transaction.atomic
def assign_episode(actor, pk, episode_id):
    require_role(actor, "operator", "admin")
    episode_id = episode_key(episode_id)
    obj = get_request(actor, pk, locked=True)
    if obj.status != "in_progress":
        raise DomainError(
            "Assignments may change only while the request is in progress.", 409
        )
    try:
        ep = Episode.objects.select_for_update().get(pk=episode_id)
    except Episode.DoesNotExist:
        raise DomainError("Episode not found.", 404)
    if ep.quality not in ["good", "usable"]:
        raise DomainError("Only good or usable episodes may be assigned.", 409)
    if ep.task_name != normalize_task(obj.task_name):
        raise DomainError("Episode task must match the request task.", 409)
    try:
        # Separate savepoint keeps the outer transaction usable if uniqueness fails.
        with transaction.atomic():
            assignment = Assignment.objects.create(
                request=obj, episode=ep, assigned_by=actor
            )
    except IntegrityError:
        raise DomainError("This episode is already assigned to a request.", 409)
    notify(
        f"Request #{obj.pk}: episode assigned",
        f"{episode_id} was added to the dataset.",
        request=obj,
    )
    return assignment


@transaction.atomic
def unassign_episode(actor, pk, episode_id):
    require_role(actor, "operator", "admin")
    episode_id = episode_key(episode_id)
    obj = get_request(actor, pk, locked=True)
    if obj.status != "in_progress":
        raise DomainError(
            "Assignments may change only while the request is in progress.", 409
        )
    removed, _ = obj.assignments.filter(episode_id=episode_id).delete()
    if not removed:
        raise DomainError("Assignment not found.", 404)
    notify(
        f"Request #{obj.pk}: episode removed",
        f"{episode_id} was removed from the dataset.",
        request=obj,
    )


@transaction.atomic
def create_user(actor, values):
    require_role(actor, "admin")
    values = values.copy()
    password = values.pop("password")
    name = values.pop("name")
    email = values["email"]
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=email, display_name=name, password=password, **values
            )
    except IntegrityError:
        raise DomainError("A user with this email already exists.", 409)
    notify(
        "User created", f"{user.display_name} was added as {user.role}.", scope="admin"
    )
    notify(
        "Welcome to Dataset Request Desk",
        "Follow your activity here and choose whether to receive email updates.",
        scope="personal",
        recipient=user,
    )
    return user


@transaction.atomic
def change_user(actor, pk, values):
    serialize_mutation(101)
    require_role(actor, "admin")
    try:
        user = User.objects.select_for_update().get(pk=pk)
    except User.DoesNotExist:
        raise DomainError("User not found.", 404)
    before = (
        user.display_name,
        user.email,
        user.organisation,
        user.role,
        user.is_active,
    )
    role = values.get("role", user.role)
    active = values.get("is_active", user.is_active)
    profile = {
        "name": user.display_name,
        "email": user.email,
        "organisation": user.organisation,
    }
    fields = {
        "name": forms.CharField(max_length=120),
        "email": forms.EmailField(max_length=150),
        "organisation": forms.CharField(max_length=120, required=False),
    }
    errors = {}
    for field, validator in fields.items():
        if field not in values:
            continue
        if not isinstance(values[field], str):
            errors[field] = ["Enter text for this field."]
            continue
        try:
            profile[field] = validator.clean(values[field])
        except forms.ValidationError as exc:
            errors[field] = exc.messages
    if errors:
        raise DomainError(errors)
    profile["email"] = profile["email"].lower()
    if (
        User.objects.exclude(pk=user.pk)
        .filter(
            Q(email__iexact=profile["email"]) | Q(username__iexact=profile["email"])
        )
        .exists()
    ):
        raise DomainError({"email": ["A user with this email already exists."]}, 409)
    if role not in User.Role.values or type(active) is not bool:
        raise DomainError("Use a valid role and a boolean is_active.")
    if user.pk == actor.pk and (role != "admin" or not active):
        raise DomainError("You cannot remove your own admin access.")
    if (
        user.role == "admin"
        and user.is_active
        and (role != "admin" or not active)
        and User.objects.filter(role="admin", is_active=True).count() <= 1
    ):
        raise DomainError("Keep at least one active administrator.")
    user.role, user.is_active = role, active
    user.display_name = profile["name"]
    user.email = user.username = profile["email"]
    user.organisation = profile["organisation"]
    if before[1] != user.email:
        # A changed address must be opted in again by the signed-in account.
        user.email_notifications = False
    try:
        with transaction.atomic():
            user.save(
                update_fields=[
                    "role",
                    "is_active",
                    "display_name",
                    "email",
                    "username",
                    "organisation",
                    "email_notifications",
                ]
            )
    except IntegrityError:
        raise DomainError({"email": ["A user with this email already exists."]}, 409)
    if before != (
        user.display_name,
        user.email,
        user.organisation,
        user.role,
        user.is_active,
    ):
        notify(
            "User updated",
            f"Account information for {user.display_name} was updated.",
            scope="admin",
        )
        notify(
            "Your account was updated",
            "An administrator updated your account information. Contact them if you need help.",
            scope="personal",
            recipient=user,
        )
    return user


@transaction.atomic
def delete_user(actor, pk, confirm_email):
    serialize_mutation(101)
    require_role(actor, "admin")
    try:
        user = User.objects.select_for_update().get(pk=pk)
    except User.DoesNotExist:
        raise DomainError("User not found.", 404)
    if user.pk == actor.pk:
        raise DomainError("You cannot delete your own admin account.")
    if (
        user.role == "admin"
        and user.is_active
        and User.objects.filter(role="admin", is_active=True).count() <= 1
    ):
        raise DomainError("Keep at least one active administrator.")
    if (
        not isinstance(confirm_email, str)
        or confirm_email.strip().lower() != user.email.lower()
    ):
        raise DomainError(
            {
                "confirm_email": [
                    "Type this account's email address to confirm deletion."
                ]
            }
        )
    name = user.display_name
    try:
        user.delete()
    except ProtectedError:
        raise DomainError(
            "This user has requests or audit history and cannot be deleted. Deactivate the account to remove access while preserving those records.",
            409,
        )
    notify("User deleted", f"The unused account for {name} was deleted.", scope="admin")
