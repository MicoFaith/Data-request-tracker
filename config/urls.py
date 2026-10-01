from django.urls import path

from desk import api, views

urlpatterns = [
    path("login/", views.login_page, name="login"),
    path("logout/", views.logout_page, name="logout"),
    path("", views.home, name="home"),
    path("requests/new/", views.new_request, name="new_request"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/status/", views.status_action, name="status_action"),
    path(
        "requests/<int:pk>/assign/", views.assignment_action, name="assignment_action"
    ),
    path("episodes/", views.episodes_page, name="episodes_page"),
    path("analytics/", views.analytics_page, name="analytics_page"),
    path("users/", views.users_page, name="users_page"),
    path("notifications/", views.notifications_page, name="notifications_page"),
    path("api/notifications/", api.notifications),
    path("api/notifications/preferences/", api.notification_preferences),
    path("health", api.health),
    path("api/login/", api.api_login),
    path("api/logout/", api.api_logout),
    path("api/me/", api.me),
    path("api/session/", api.session),
    path("api/dashboard/", api.dashboard),
    path("api/requests/", api.requests),
    path("api/requests/<int:pk>/", api.detail),
    path("api/requests/<int:pk>/status/", api.change_status),
    path("api/requests/<int:pk>/assignments/", api.assignments),
    path("api/requests/<int:pk>/assignments/<str:eid>/", api.remove_assignment),
    path("api/episodes/", api.episodes),
    path("api/episodes/import/", api.upload),
    path("api/analytics/", api.metrics),
    path("api/users/", api.users),
    path("api/users/<int:pk>/", api.user_update),
]
handler500 = "desk.views.server_error"
