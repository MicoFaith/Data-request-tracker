import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings
from .email_backend import BrevoBackend


@override_settings(BREVO_API_KEY="test-api-key", EMAIL_TIMEOUT=20)
class BrevoBackendTests(SimpleTestCase):
    def message(self):
        return EmailMessage(
            "Update", "Open your inbox", "desk@example.com", ["approved@example.com"]
        )

    @patch("desk.email_backend.urlopen")
    def test_https_transport_uses_verified_sender_and_returns_acceptance(self, send):
        send.return_value.__enter__.return_value.status = 201
        self.assertEqual(BrevoBackend().send_messages([self.message()]), 1)
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(request.get_header("Api-key"), "test-api-key")
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], [{"email": "approved@example.com"}])
        self.assertEqual(payload["textContent"], "Open your inbox")
        self.assertEqual(send.call_args.kwargs["timeout"], 20)

    @patch(
        "desk.email_backend.urlopen",
        side_effect=HTTPError("https://api.brevo.com", 429, "rate limited", {}, None),
    )
    def test_provider_failure_reaches_outbox_retry_handler(self, send):
        with self.assertRaises(HTTPError):
            BrevoBackend().send_messages([self.message()])
        self.assertEqual(
            BrevoBackend(fail_silently=True).send_messages([self.message()]), 0
        )
