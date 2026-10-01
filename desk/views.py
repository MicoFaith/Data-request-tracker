import functools
import io
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from . import api
from .analytics import analytics
from .forms import (
    AnalyticsFilterForm,
    EpisodeFilterForm,
    NewUserForm,
    RequestFilterForm,
    RequestForm,
    UserFilterForm,
    kigali_today,
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


def filtered_page(query, params, form):
    """Keep invalid filters editable on their original screen."""
    if not form.is_valid():
        query = query.none()
    try:
        return api.page(query, params)
    except DomainError as exc:
        form.add_error(None, exc.message)
        return api.page(query.none(), {})


def paging_context(request, meta):
    params = request.GET.copy()
    params.pop("page", None)
    return {"meta": meta, "page_query": params.urlencode()}


def protected(*roles):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            try:
                require_role(request.user, *(roles or User.Role.values))
                return fn(request, *args, **kwargs)
            except DomainError as exc:
                return render(
                    request,
                    "desk/error.html",
                    {"error": exc.message},
                    status=exc.status,
                )

        return wrapped

    return decorate


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login_page(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        user = (
            authenticate(request, username=email, password=password)
            if len(email) <= 254 and len(password) <= 128
            else None
        )
        if user:
            login(request, user)
            return redirect("home")
        error = "Invalid email or password."
    return render(
        request,
        "desk/login.html",
        {"error": error, "email": request.POST.get("email", "")[:254]},
        status=401 if error else 200,
    )


@protected()
@require_http_methods(["POST"])
def logout_page(request):
    logout(request)
    return redirect("login")


@protected()
@require_http_methods(["GET"])
def home(request):
    today = kigali_today()
    scope = DatasetRequest.objects.all()
    if request.user.role == "client":
        scope = scope.filter(client=request.user)
    stats = scope.aggregate(
        total=Count("pk"),
        **{s: Count("pk", filter=Q(status=s)) for s in DatasetRequest.Status.values},
        overdue=Count("pk", filter=Q(deadline__lt=today) & ~Q(status="accepted")),
    )
    if request.user.role == "client":
        cards = [
            ("All requests", stats["total"], "", "Your full request history"),
            (
                "Awaiting review",
                stats["delivered"],
                "status=delivered",
                "Ready for your decision",
            ),
            (
                "In progress",
                stats["in_progress"],
                "status=in_progress",
                "Being prepared by operations",
            ),
            ("Accepted", stats["accepted"], "status=accepted", "Completed deliveries"),
        ]
    else:
        cards = [
            (
                "Ready to start",
                stats["submitted"],
                "status=submitted",
                "New client requests",
            ),
            (
                "In progress",
                stats["in_progress"],
                "status=in_progress",
                "Assignments in motion",
            ),
            (
                "Needs rework",
                stats["rejected"],
                "status=rejected",
                "Return to the fulfilment queue",
            ),
            (
                "Overdue",
                stats["overdue"],
                "attention=overdue&sort=deadline",
                "Past deadline, not yet accepted",
            ),
        ]
    form = RequestFilterForm(request.GET)
    query = visible_requests(request.user)
    if form.is_valid():
        values = form.cleaned_data
        if values["status"]:
            query = query.filter(status=values["status"])
        if values["attention"] == "overdue":
            query = query.filter(deadline__lt=today).exclude(status="accepted")
        if values["q"]:
            match = Q(task_name__icontains=values["q"])
            if request.user.role != "client":
                match |= Q(client__display_name__icontains=values["q"])
            digits = values["q"].lstrip("#")
            if digits.isascii() and digits.isdigit() and len(digits) <= 18:
                match |= Q(pk=int(digits))
            query = query.filter(match)
        if values["sort"] == "deadline":
            query = query.order_by("deadline", "-pk")
    rows, meta = filtered_page(query, request.GET, form)
    return render(
        request,
        "desk/home.html",
        {
            "rows": rows,
            **paging_context(request, meta),
            "filter_form": form,
            "status": request.GET.get("status", ""),
            "status_label": dict(DatasetRequest.Status.choices).get(
                request.GET.get("status"), "Request overview"
            ),
            "statuses": DatasetRequest.Status.choices,
            "stats": stats,
            "cards": cards,
            "today": today,
            "active_users": (
                User.objects.filter(is_active=True).count()
                if request.user.role == "admin"
                else None
            ),
        },
    )


@protected("client")
@require_http_methods(["GET", "POST"])
def new_request(request):
    form = RequestForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            obj = create_request(request.user, form.cleaned_data)
        except DomainError:
            form.add_error(None, "Please check the deadline and try again.")
        else:
            messages.success(
                request,
                f"Request #{obj.pk} submitted. The operations team can now begin fulfilment.",
            )
            return redirect("request_detail", pk=obj.pk)
    return render(request, "desk/new.html", {"form": form})


@protected()
@require_http_methods(["GET"])
def request_detail(request, pk):
    obj = get_request(request.user, pk)
    assigned = list(obj.assignments.select_related("episode", "assigned_by"))
    events = obj.events.select_related("actor")
    candidates = []
    meta = {}
    filter_form = EpisodeFilterForm(request.GET)
    if request.user.role != "client" and obj.status == "in_progress":
        params = request.GET.copy()
        params.setdefault("task_name", obj.task_name)
        params["available"] = "true"
        filter_form = EpisodeFilterForm(params)
        query = (
            api.episode_query(params)
            if filter_form.is_valid()
            else Episode.objects.none()
        )
        candidates, meta = filtered_page(query, params, filter_form)
    return render(
        request,
        "desk/detail.html",
        {
            "obj": obj,
            "assigned": assigned,
            "events": events,
            "candidates": candidates,
            **paging_context(request, meta),
            "filter_form": filter_form,
            "today": kigali_today(),
            "remaining": max(0, obj.episodes_requested - len(assigned)),
            "history": [
                {
                    "label": dict(DatasetRequest.Status.choices).get(
                        e.to_status, e.to_status
                    ),
                    "actor": e.actor,
                    "at": e.at,
                }
                for e in events.select_related("actor")
            ],
            "task_name": request.GET.get("task_name", obj.task_name),
            "quality": request.GET.get("quality", ""),
        },
    )


@protected()
@require_http_methods(["POST"])
def status_action(request, pk):
    try:
        obj = transition(request.user, pk, request.POST.get("status", ""))
        messages.success(
            request, f"Request #{obj.pk} is now {obj.get_status_display().lower()}."
        )
    except DomainError as exc:
        messages.error(request, str(exc.message))
    return redirect("request_detail", pk=pk)


@protected("operator", "admin")
@require_http_methods(["POST"])
def assignment_action(request, pk):
    try:
        if request.POST.get("remove") not in [None, "true"]:
            raise DomainError("Invalid assignment action.")
        if request.POST.get("remove") == "true":
            unassign_episode(request.user, pk, request.POST.get("episode_id", ""))
            messages.success(request, "Episode released.")
        else:
            assign_episode(request.user, pk, request.POST.get("episode_id", ""))
            messages.success(request, "Episode assigned.")
    except DomainError as exc:
        messages.error(request, str(exc.message))
    # Preserve the operator's filters while assigning several episodes.
    params = request.GET.copy()
    params.pop("page", None)
    target = reverse("request_detail", args=[pk])
    if params:
        target += "?" + params.urlencode()
    return redirect(target + "#assignment-panel")


@protected("operator", "admin")
@require_http_methods(["GET", "POST"])
def episodes_page(request):
    report = None
    error = ""
    if request.method == "POST":
        file = request.FILES.get("file")
        try:
            if not file:
                raise DomainError("Choose a CSV file.")
            if file.size > 10 * 1024 * 1024:
                raise DomainError("Upload limit is 10 MiB.")
            report = import_episodes(
                request.user,
                io.TextIOWrapper(file.file, encoding="utf-8-sig", newline=""),
            )
        except DomainError as exc:
            error = exc.message
    form = EpisodeFilterForm(request.GET)
    query = (
        api.episode_query(request.GET) if form.is_valid() else Episode.objects.none()
    )
    rows, meta = filtered_page(query, request.GET, form)
    inventory = Episode.objects.aggregate(
        total=Count("pk"),
        eligible=Count(
            "pk", filter=Q(quality__in=["good", "usable"], assignment__isnull=True)
        ),
        assigned=Count("pk", filter=Q(assignment__isnull=False)),
    )
    return render(
        request,
        "desk/episodes.html",
        {
            "rows": rows,
            **paging_context(request, meta),
            "filter_form": form,
            "inventory": inventory,
            "report": report,
            "error": error,
            "task_name": request.GET.get("task_name", ""),
            "quality": request.GET.get("quality", ""),
            "available": request.GET.get("available", ""),
        },
    )


@protected("operator", "admin")
@require_http_methods(["GET"])
def analytics_page(request):
    params = request.GET.copy()
    today = kigali_today()
    params.setdefault("start", (today - timedelta(days=90)).isoformat())
    params.setdefault("end", today.isoformat())
    form = AnalyticsFilterForm(params)
    result = (
        analytics(form.cleaned_data["start"], form.cleaned_data["end"])
        if form.is_valid()
        else None
    )
    status_cards = (
        []
        if result is None
        else [
            (label, result["request_fulfilment"]["counts_by_status"][key])
            for key, label in DatasetRequest.Status.choices
        ]
    )
    return render(
        request,
        "desk/analytics.html",
        {
            "result": result,
            "form": form,
            "status_cards": status_cards,
            "today": today.isoformat(),
            "month_start": (today - timedelta(days=29)).isoformat(),
        },
    )


@protected("admin")
@require_http_methods(["GET", "POST"])
def users_page(request):
    form = (
        NewUserForm(request.POST if request.method == "POST" else None)
        if not request.POST.get("user_id")
        else NewUserForm()
    )
    if request.method == "POST":
        try:
            if request.POST.get("user_id"):
                if request.POST.get("action") == "delete":
                    delete_user(
                        request.user,
                        int(request.POST["user_id"]),
                        request.POST.get("confirm_email"),
                    )
                    messages.success(request, "User deleted.")
                    return redirect(request.get_full_path())
                if request.POST.get("is_active") not in [None, "true"]:
                    raise DomainError(
                        "Invalid active setting; reload the form and retry."
                    )
                change_user(
                    request.user,
                    int(request.POST["user_id"]),
                    {
                        "role": request.POST.get("role"),
                        "is_active": request.POST.get("is_active") == "true",
                        **{
                            key: request.POST[key]
                            for key in ["name", "email", "organisation"]
                            if key in request.POST
                        },
                    },
                )
                messages.success(request, "User updated.")
                return redirect(request.get_full_path())
            if form.is_valid():
                create_user(request.user, form.cleaned_data)
                messages.success(request, "User created.")
                return redirect("users_page")
        except (DomainError, ValueError) as exc:
            detail = getattr(exc, "message", "Invalid user input.")
            error = (
                "; ".join(
                    f"{field.replace('_', ' ').title()}: {' '.join(values)}"
                    for field, values in detail.items()
                )
                if isinstance(detail, dict)
                else str(detail)
            )
            if not request.POST.get("user_id"):
                form.add_error(
                    (
                        "email"
                        if isinstance(exc, DomainError) and exc.status == 409
                        else None
                    ),
                    error,
                )
            else:
                messages.error(request, error)
    filters = UserFilterForm(request.GET)
    query = User.objects.order_by("pk")
    if filters.is_valid():
        values = filters.cleaned_data
        if values["q"]:
            query = query.filter(
                Q(email__icontains=values["q"]) | Q(display_name__icontains=values["q"])
            )
        if values["role"]:
            query = query.filter(role=values["role"])
        if values["active"]:
            query = query.filter(is_active=values["active"] == "true")
    rows, meta = filtered_page(query, request.GET, filters)
    rows = list(rows)
    for item in rows:
        editing = request.method == "POST" and request.POST.get("user_id") == str(
            item.pk
        )
        for field, current in [
            ("name", item.display_name),
            ("email", item.email),
            ("organisation", item.organisation),
        ]:
            setattr(
                item,
                f"edit_{field}",
                request.POST.get(field, current) if editing else current,
            )
    return render(
        request,
        "desk/users.html",
        {
            "form": form,
            "rows": rows,
            "roles": User.Role.choices,
            "filter_form": filters,
            **paging_context(request, meta),
            "user_stats": User.objects.aggregate(
                total=Count("pk"),
                active=Count("pk", filter=Q(is_active=True)),
                admins=Count("pk", filter=Q(role="admin", is_active=True)),
            ),
        },
    )


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        return JsonResponse(
            {
                "error": "CSRF validation failed. Get /login/ and send the csrf token with your session."
            },
            status=403,
        )
    return render(
        request,
        "desk/error.html",
        {"error": "Your security token expired. Reload the page and retry."},
        status=403,
    )


def server_error(request):
    if request.path.startswith("/api/"):
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)
    return render(
        request,
        "desk/error.html",
        {"error": "An unexpected error occurred. Please retry."},
        status=500,
    )


@ensure_csrf_cookie
@protected()
@require_http_methods(["GET"])
def notifications_page(request):
    from .notifications import visible_notifications

    rows, _ = api.page(visible_notifications(request.user), {})
    return render(request, "desk/notifications.html", {"notifications": rows})
