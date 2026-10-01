#!/bin/sh
set -eu
mkdir -p data
if [ "${DJANGO_SETTINGS_MODULE:-}" = "config.production" ] || [ "${DJANGO_SETTINGS_MODULE:-}" = "config.render" ]; then
    python manage.py check --deploy --fail-level WARNING
fi
python manage.py migrate --noinput
if [ "${SEED_DEMO:-1}" = "1" ]; then
    python manage.py seed_demo --once
fi
python manage.py collectstatic --noinput
if [ "${RUN_NOTIFICATION_WORKER:-0}" = "1" ]; then
    exec python scripts/serve.py
fi
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 60
