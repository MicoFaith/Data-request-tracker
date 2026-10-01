import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# The clean-clone test command also needs a writable database directory.
(BASE_DIR / "data").mkdir(exist_ok=True)
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "local-demo-only-replace-before-public-deployment"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"
).split(",")
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "desk",
]
MIDDLEWARE = [
    "desk.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "desk.frontend.assets",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "data/db.sqlite3"),
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
        "TEST": {"NAME": BASE_DIR / "data/test.sqlite3"},
    }
}
AUTH_USER_MODEL = "desk.User"
if os.environ.get("DATABASE_URL"):
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            os.environ["DATABASE_URL"],
            conn_max_age=0,
            conn_health_checks=True,
            ssl_require=os.environ.get("DJANGO_SETTINGS_MODULE") == "config.render",
        )
    }
    if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        raise ValueError("DATABASE_URL must use PostgreSQL.")
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
TIME_ZONE = "Africa/Kigali"
USE_TZ = True
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
CSRF_FAILURE_VIEW = "desk.views.csrf_failure"
NOTIFICATION_EMAIL_ENABLED = os.environ.get("NOTIFICATION_EMAIL_ENABLED", "0") == "1"
NOTIFICATION_EMAIL_RECIPIENTS = [
    email.strip().lower()
    for email in os.environ.get("NOTIFICATION_EMAIL_RECIPIENTS", "").split(",")
    if email.strip()
]
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "smtp")
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
EMAIL_BACKEND = (
    "desk.email_backend.BrevoBackend"
    if EMAIL_PROVIDER == "brevo"
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "0") == "1"
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000")
if NOTIFICATION_EMAIL_ENABLED:
    from urllib.parse import urlsplit
    from django.core.exceptions import ImproperlyConfigured, ValidationError
    from django.core.validators import validate_email

    try:
        validate_email(DEFAULT_FROM_EMAIL)
        for approved in NOTIFICATION_EMAIL_RECIPIENTS:
            validate_email(approved)
    except ValidationError as exc:
        raise ImproperlyConfigured(
            "Set valid DEFAULT_FROM_EMAIL and NOTIFICATION_EMAIL_RECIPIENTS addresses."
        ) from exc
    base = urlsplit(APP_BASE_URL)
    if EMAIL_PROVIDER not in ("smtp", "brevo"):
        raise ImproperlyConfigured("EMAIL_PROVIDER must be smtp or brevo.")
    if EMAIL_PROVIDER == "brevo" and not BREVO_API_KEY:
        raise ImproperlyConfigured("Set BREVO_API_KEY for email delivery.")
    if EMAIL_PROVIDER == "smtp" and (
        not EMAIL_HOST
        or not 1 <= EMAIL_PORT <= 65535
        or (EMAIL_USE_TLS and EMAIL_USE_SSL)
    ):
        raise ImproperlyConfigured(
            "Configure EMAIL_HOST, a valid EMAIL_PORT and only one of TLS/SSL."
        )
    if (
        base.scheme not in ("http", "https")
        or not base.hostname
        or base.username
        or base.password
        or base.query
        or base.fragment
        or base.path not in ("", "/")
    ):
        raise ImproperlyConfigured("APP_BASE_URL must be the absolute site origin.")
    if base.scheme != "https" and base.hostname not in ("localhost", "127.0.0.1"):
        raise ImproperlyConfigured("Public notification links require HTTPS.")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "desk.requests": {"handlers": ["console"], "level": "INFO", "propagate": False}
    },
}
