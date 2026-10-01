import os
import secrets
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class PublicDeploymentSettingsTests(SimpleTestCase):
    def check_settings(self, **changes):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.production",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
            "DJANGO_ALLOWED_HOSTS": "demo.example.com",
            "NOTIFICATION_EMAIL_ENABLED": "0",
            "DATABASE_URL": "",
            **changes,
        }
        return subprocess.run(
            [
                sys.executable,
                "manage.py",
                "check",
                "--deploy",
                "--fail-level",
                "WARNING",
            ],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_public_settings_pass_security_checks(self):
        result = self.check_settings()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_startup_refuses_missing_secret(self):
        result = self.check_settings(DJANGO_SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set a random DJANGO_SECRET_KEY", result.stderr)

    def test_public_startup_refuses_wildcard_hosts(self):
        for host in ["*", "*.example.com", ".example.com"]:
            with self.subTest(host=host):
                result = self.check_settings(DJANGO_ALLOWED_HOSTS=host)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Set explicit DJANGO_ALLOWED_HOSTS", result.stderr)

    def email_settings(self, **changes):
        return self.check_settings(
            NOTIFICATION_EMAIL_ENABLED="1",
            EMAIL_HOST="smtp.example.com",
            DEFAULT_FROM_EMAIL="desk@example.com",
            APP_BASE_URL="https://demo.example.com",
            EMAIL_USE_TLS="1",
            EMAIL_USE_SSL="0",
            SEED_DEMO="1",
            **changes
        )

    def test_public_demo_mail_requires_approved_recipients(self):
        result = self.email_settings(NOTIFICATION_EMAIL_RECIPIENTS="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Public demo email requires", result.stderr)

    def test_public_demo_mail_with_allowlist_passes(self):
        result = self.email_settings(NOTIFICATION_EMAIL_RECIPIENTS="tester@example.com")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_allowlist_is_rejected(self):
        result = self.email_settings(NOTIFICATION_EMAIL_RECIPIENTS="not-an-email")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set valid DEFAULT_FROM_EMAIL", result.stderr)

    def test_render_uses_managed_hostname_and_passes_security_checks(self):
        result = self.check_settings(
            DJANGO_SETTINGS_MODULE="config.render",
            RENDER_EXTERNAL_HOSTNAME="data-request-tracker.onrender.com",
            DATABASE_URL="postgresql://demo:demo@localhost/demo?sslmode=require",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_render_refuses_missing_platform_hostname(self):
        result = self.check_settings(
            DJANGO_SETTINGS_MODULE="config.render", RENDER_EXTERNAL_HOSTNAME=""
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RENDER_EXTERNAL_HOSTNAME", result.stderr)

    def test_render_accepts_generated_256_bit_secret(self):
        import base64

        result = self.check_settings(
            DJANGO_SETTINGS_MODULE="config.render",
            RENDER_EXTERNAL_HOSTNAME="data-request-tracker.onrender.com",
            DJANGO_SECRET_KEY=base64.b64encode(os.urandom(32)).decode(),
            DATABASE_URL="postgresql://demo:demo@localhost/demo?sslmode=require",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
