import functools
import io
import json
import re

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError, connection
from django.db.models import Count, Q
from django.middleware.csrf import get_token
from django.utils import timezone
from django.http import JsonResponse

from .analytics import analytics
from .forms import (
    NewUserForm,
    RequestFilterForm,
    UserFilterForm,
    EpisodeFilterForm,
    normalize_task,
)
from .importer import import_episodes
from .models import DatasetRequest, Episode, User
from .services import (
    DomainError,
    assign_episode,
    change_user,
    create_request,
    create_user,
    delete_user,
    get_request,
    require_role,
    transition,
    unassign_episode,
    visible_requests,
)


def api(methods, public=False):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(request, *args, **kwargs):
            try:
                if not public:
                    require_role(request.user, *User.Role.values)
                if request.method not in methods:
                    response = JsonResponse(
                        {"error": "Method not allowed."}, status=405
                    )
                    response["Allow"] = ", ".join(methods)
                    return response
                return fn(request, *args, **kwargs)
            except DomainError as exc:
                return JsonResponse({"error": exc.message}, status=exc.status)
            except RequestDataTooBig:
                return JsonResponse({"error": "Upload limit is 10 MiB."}, status=413)
            except DatabaseError:
                return JsonResponse(
                    {"error": "Database operation unavailable; retry later."},
                    status=503,
                )

        return wrapped

    return decorate


def body(request, allowed=None):
    if request.content_type != "application/json":
        raise DomainError("Use application/json.", 415)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite JSON number.")

    try:
        data = json.loads(
            request.body,
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError("Malformed JSON.", 400)
    if not isinstance(data, dict):
        raise DomainError("Expected a JSON object.", 400)
    if allowed is not None and set(data) - set(allowed):
        raise DomainError("Unknown fields in request.")
    return data


def validate(form):
    if not form.is_valid():
        raise DomainError(
            {key: [str(v) for v in values] for key, values in form.errors.items()}
        )
    return form.cleaned_data


def page(query, params):
    try:
        p = int(params.get("page", 1))
    except (ValueError, TypeError):
        raise DomainError("page must be a positive integer.")
    if not 1 <= p <= 100000:
        raise DomainError("page must be between 1 and 100000.")
    size = 50
    count = query.count()
    return query[(p - 1) * size : p * size], {
        "page": p,
        "page_size": size,
        "total": count,
        "has_next": p * size < count,
    }


def user_data(user):
    return {
        "id": user.pk,
        "email": user.email,
        "name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "organisation": user.organisation,
    }


def request_data(obj):
    return {
        "id": obj.pk,
        "client_id": obj.client_id,
        "client_name": obj.client.display_name,
        "task_name": obj.task_name,
        "episodes_requested": obj.episodes_requested,
        "deadline": obj.deadline,
        "notes": obj.notes,
        "status": obj.status,
        "created_at": obj.created_at,
        "first_delivered_at": obj.first_delivered_at,
        "assigned_count": (
            obj.assigned_count
            if hasattr(obj, "assigned_count")
            else obj.assignments.count()
        ),
    }


def episode_data(ep):
    return {
        "episode_id": ep.pk,
        "robot_id": ep.robot_id,
        "task_name": ep.task_name,
        "recorded_at": ep.recorded_at,
        "duration_seconds": ep.duration_seconds,
        "operator_name": ep.operator_name,
        "quality": ep.quality,
    }


def episode_query(params):
    validate(EpisodeFilterForm(params))
    query = Episode.objects.all()
    task = params.get("task_name", "").strip()
    quality = params.get("quality", "")
    if task:
        query = query.filter(task_name=normalize_task(task))
    if quality:
        if quality not in ["good", "usable", "bad"]:
            raise DomainError("quality must be good, usable or bad.")
        query = query.filter(quality=quality)
    available = params.get("available", "")
    if available not in ["", "true", "false"]:
        raise DomainError("available must be true or false.")
    if available:
        query = query.filter(assignment__isnull=available == "true")
    return query


def dates(params):
    from datetime import date

    try:
        if any(
            not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", params[key])
            for key in ["start", "end"]
        ):
            raise ValueError
        start = date.fromisoformat(params["start"])
        end = date.fromisoformat(params["end"])
    except (KeyError, ValueError, TypeError):
        raise DomainError("Use start and end as YYYY-MM-DD.")
    if start > end or start.year < 2 or end.year == 9999:
        raise DomainError("Use an ordered, bounded date range.")
    return start, end


@api(["POST"], public=True)
def api_login(request):
    data = body(request, {"email", "password"})
    email = data.get("email", "")
    password = data.get("password", "")
    if (
        not isinstance(email, str)
        or not isinstance(password, str)
        or len(email) > 254
        or len(password) > 128
    ):
        raise DomainError("Invalid login input.")
    user = authenticate(request, username=email.strip().lower(), password=password)
    if user is None:
        raise DomainError("Invalid email or password.", 401)
    login(request, user)
    return JsonResponse({"user": user_data(user)})


@api(["POST"])
def api_logout(request):
    logout(request)
    return JsonResponse({"ok": True})


@api(["GET"])
def me(request):
    return JsonResponse({"user": user_data(request.user)})


@api(["GET"], public=True)
def session(request):
    from datetime import timedelta

    today = timezone.localdate()
    response = JsonResponse(
        {
            "user": user_data(request.user) if request.user.is_authenticated else None,
            "csrf": get_token(request),
            "today": today,
            "tomorrow": today + timedelta(days=1),
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@api(["GET"])
def dashboard(request):
    query = DatasetRequest.objects.all()
    if request.user.role == "client":
        query = query.filter(client=request.user)
    counts = query.aggregate(
        total=Count("pk"),
        overdue=Count(
            "pk", filter=Q(deadline__lt=timezone.localdate()) & ~Q(status="accepted")
        ),
        **{s: Count("pk", filter=Q(status=s)) for s in DatasetRequest.Status.values},
    )
    result = {"counts": counts}
    if request.user.role != "client":
        result["inventory"] = Episode.objects.aggregate(
            total=Count("pk"),
            assigned=Count("pk", filter=Q(assignment__isnull=False)),
            eligible=Count(
                "pk", filter=Q(assignment__isnull=True, quality__in=["good", "usable"])
            ),
        )
    if request.user.role == "admin":
        result["people"] = User.objects.aggregate(
            total=Count("pk"), active=Count("pk", filter=Q(is_active=True))
        )
    return JsonResponse(result)


@api(["GET", "POST"])
def requests(request):
    if request.method == "POST":
        require_role(request.user, "client")
        data = body(request)
        if type(data.get("episodes_requested")) is not int:
            raise DomainError("episodes_requested must be an integer.")
        if any(
            key in data and not isinstance(data[key], str)
            for key in ["task_name", "deadline", "notes"]
        ):
            raise DomainError("task_name, deadline and notes must be strings.")
        if set(data) - {"task_name", "episodes_requested", "deadline", "notes"}:
            raise DomainError(
                "Unknown request fields; ownership is determined from your login."
            )
        obj = create_request(request.user, data)
        return JsonResponse({"request": request_data(obj)}, status=201)
    query = visible_requests(request.user)
    filters = validate(RequestFilterForm(request.GET))
    search = filters.get("q")
    if search:
        match = Q(task_name__icontains=search)
        if request.user.role != "client":
            match |= Q(client__display_name__icontains=search)
        if search.lstrip("#").isdigit() and len(search.lstrip("#")) <= 18:
            match |= Q(pk=int(search.lstrip("#")))
        query = query.filter(match)
    if filters.get("attention") == "overdue":
        query = query.filter(deadline__lt=timezone.localdate()).exclude(
            status="accepted"
        )
    if filters.get("sort") == "deadline":
        query = query.order_by("deadline", "-pk")
    status = request.GET.get("status", "")
    if status:
        if status not in DatasetRequest.Status.values:
            raise DomainError("Invalid status filter.")
        query = query.filter(status=status)
    rows, meta = page(query, request.GET)
    return JsonResponse({"requests": [request_data(obj) for obj in rows], **meta})


@api(["GET"])
def detail(request, pk):
    obj = get_request(request.user, pk)
    return JsonResponse(
        {
            "request": request_data(obj),
            "episodes": [
                episode_data(a.episode)
                for a in obj.assignments.select_related("episode")
            ],
            "history": [
                {
                    "from_status": e.from_status,
                    "to_status": e.to_status,
                    "actor_id": e.actor_id,
                    "actor_name": e.actor.display_name,
                    "at": e.at,
                }
                for e in obj.events.select_related("actor")
            ],
        }
    )


@api(["POST"])
def change_status(request, pk):
    data = body(request, {"status"})
    status = data.get("status")
    if status not in DatasetRequest.Status.values:
        raise DomainError("Invalid status.")
    return JsonResponse({"request": request_data(transition(request.user, pk, status))})


@api(["POST"])
def assignments(request, pk):
    data = body(request, {"episode_id"})
    eid = data.get("episode_id")
    if not isinstance(eid, str) or len(eid) > 40:
        raise DomainError("Provide an episode_id string.")
    assignment = assign_episode(request.user, pk, eid)
    return JsonResponse(
        {"episode_id": assignment.episode_id, "request_id": assignment.request_id},
        status=201,
    )


@api(["DELETE"])
def remove_assignment(request, pk, eid):
    unassign_episode(request.user, pk, eid)
    return JsonResponse({"ok": True})


@api(["GET"])
def episodes(request):
    require_role(request.user, "operator", "admin")
    rows, meta = page(episode_query(request.GET), request.GET)
    return JsonResponse({"episodes": [episode_data(ep) for ep in rows], **meta})


@api(["POST"])
def upload(request):
    require_role(request.user, "operator", "admin")
    file = request.FILES.get("file")
    if not file:
        raise DomainError("Upload a CSV file in the file field.")
    if file.size > 10 * 1024 * 1024:
        raise DomainError("Upload limit is 10 MiB.", 413)
    return JsonResponse(
        import_episodes(
            request.user, io.TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
        )
    )


@api(["GET"])
def metrics(request):
    require_role(request.user, "operator", "admin")
    return JsonResponse(analytics(*dates(request.GET)))


@api(["GET", "POST"])
def users(request):
    require_role(request.user, "admin")
    if request.method == "POST":
        data = body(request)
        if set(data) - {"email", "name", "organisation", "role", "password"} or any(
            not isinstance(v, str) for v in data.values()
        ):
            raise DomainError("Use string values for valid user fields.")
        return JsonResponse(
            {"user": user_data(create_user(request.user, validate(NewUserForm(data))))},
            status=201,
        )
    filters = validate(UserFilterForm(request.GET))
    query = User.objects.order_by("pk")
    if filters.get("q"):
        query = query.filter(
            Q(email__icontains=filters["q"]) | Q(display_name__icontains=filters["q"])
        )
    if filters.get("role"):
        query = query.filter(role=filters["role"])
    if filters.get("active"):
        query = query.filter(is_active=filters["active"] == "true")
    rows, meta = page(query, request.GET)
    return JsonResponse({"users": [user_data(u) for u in rows], **meta})


@api(["PATCH", "DELETE"])
def user_update(request, pk):
    require_role(request.user, "admin")
    if request.method == "DELETE":
        data = body(request, {"confirm_email"})
        delete_user(request.user, pk, data.get("confirm_email"))
        return JsonResponse({"ok": True})
    data = body(request)
    if not data or set(data) - {"role", "is_active", "name", "email", "organisation"}:
        raise DomainError("Use name, email, organisation, role and/or is_active.")
    return JsonResponse({"user": user_data(change_user(request.user, pk, data))})


@api(["GET"])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "database": "ok"})


@api(["GET", "POST"])
def notifications(request):
    from .notifications import notification_path, visible_notifications

    query = visible_notifications(request.user)
    if request.method == "POST":
        data = body(request, {"id", "all"})
        if data == {"all": True}:
            query.filter(read_at__isnull=True).update(read_at=timezone.now())
        elif set(data) == {"id"} and type(data["id"]) is int and data["id"] > 0:
            selected = query.filter(pk=data["id"])
            if not selected.exists():
                raise DomainError("Notification not found.", 404)
            selected.filter(read_at__isnull=True).update(read_at=timezone.now())
        else:
            raise DomainError("Provide a positive notification id or all: true.")
        return JsonResponse({"ok": True})
    unread = query.filter(read_at__isnull=True).count()
    if request.GET.get("unread", "") not in ("", "true", "false"):
        raise DomainError("unread must be true or false.")
    if request.GET.get("unread") == "true":
        query = query.filter(read_at__isnull=True)
    rows, meta = page(query, request.GET)
    return JsonResponse(
        {
            "notifications": [
                {
                    "id": n.pk,
                    "title": n.title,
                    "message": n.message,
                    "created_at": n.created_at,
                    "read": n.read_at is not None,
                    "href": notification_path(n),
                    "email_state": n.email_state,
                }
                for n in rows
            ],
            "unread_count": unread,
            **meta,
        }
    )


@api(["GET", "PATCH"])
def notification_preferences(request):
    from .notifications import email_available, set_email_preference

    if request.method == "PATCH":
        data = body(request, {"email_notifications"})
        enabled = data.get("email_notifications")
        if type(enabled) is not bool:
            raise DomainError("email_notifications must be a boolean.")
        if enabled and not email_available(request.user):
            raise DomainError(
                "Email delivery is not available for this account. Contact the administrator; in-app updates are available.",
                409,
            )
        set_email_preference(request.user, enabled)
        request.user.email_notifications = enabled
    return JsonResponse(
        {
            "email_notifications": request.user.email_notifications,
            "email_available": email_available(request.user),
            "email": request.user.email,
        }
    )
