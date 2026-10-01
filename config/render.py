"""Render's free web service with external persistent PostgreSQL."""

import os
import re
import base64
import hashlib
from django.core.exceptions import ImproperlyConfigured

hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.onrender\.com", hostname):
    raise ImproperlyConfigured("A valid RENDER_EXTERNAL_HOSTNAME is required.")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", hostname)
os.environ.setdefault("APP_BASE_URL", f"https://{hostname}")
if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
    raise ImproperlyConfigured(
        "Render requires a PostgreSQL DATABASE_URL so restarts do not lose data."
    )
os.environ.setdefault("EMAIL_PROVIDER", "brevo")

# Render generates 256-bit base64 secrets (44 characters). Preserve that entropy
# while meeting the shared production setting's minimum character length.
secret = os.environ.get("DJANGO_SECRET_KEY", "")
if len(secret) < 50:
    try:
        raw = base64.b64decode(secret, validate=True)
    except ValueError as exc:
        raise ImproperlyConfigured(
            "Use Render's generated secret or a random secret of at least 50 characters."
        ) from exc
    if len(raw) != 32 or len(set(raw)) < 5:
        raise ImproperlyConfigured(
            "Use Render's generated secret or a random secret of at least 50 characters."
        )
    os.environ["DJANGO_SECRET_KEY"] = hashlib.sha256(raw).hexdigest()

from .production import *  # noqa: E402,F403
