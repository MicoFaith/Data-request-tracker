"""HTTPS deployment behind a trusted reverse proxy; no default production secret."""

from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:
    raise ImproperlyConfigured(
        "Set a random DJANGO_SECRET_KEY of at least 50 characters."
    )
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
if not ALLOWED_HOSTS or any(
    "*" in host or "://" in host or host.startswith(".") for host in ALLOWED_HOSTS
):
    raise ImproperlyConfigured(
        "Set explicit DJANGO_ALLOWED_HOSTS domains without a scheme or wildcard."
    )
DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]
# Use only when the application port is private and the proxy replaces this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "same-origin"
if (
    NOTIFICATION_EMAIL_ENABLED
    and os.environ.get("SEED_DEMO", "1") == "1"
    and not NOTIFICATION_EMAIL_RECIPIENTS
):
    raise ImproperlyConfigured(
        "Public demo email requires NOTIFICATION_EMAIL_RECIPIENTS with approved test addresses."
    )
