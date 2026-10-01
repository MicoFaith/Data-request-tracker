"""Brevo HTTPS transport for hosts that restrict outbound SMTP ports."""

import json
from urllib.request import Request, urlopen
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class BrevoBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            payload = {
                "sender": {"email": message.from_email, "name": "Dataset Request Desk"},
                "to": [{"email": address} for address in message.recipients()],
                "subject": message.subject,
                "textContent": message.body,
            }
            request = Request(
                "https://api.brevo.com/v3/smtp/email",
                data=json.dumps(payload).encode(),
                headers={
                    "api-key": settings.BREVO_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                    if response.status != 201:
                        raise RuntimeError("Email provider did not accept the message")
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent
