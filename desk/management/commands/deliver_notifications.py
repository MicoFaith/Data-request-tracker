import time

from django.core.management.base import BaseCommand
from django.db import OperationalError, close_old_connections

from desk.notifications import deliver_batch


class Command(BaseCommand):
    help = "Deliver queued notification email; --watch polls every five seconds."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")

    def handle(self, *args, **options):
        while True:
            try:
                sent = deliver_batch()
                if sent or not options["watch"]:
                    self.stdout.write(f"Accepted by email backend: {sent}")
            except OperationalError:
                if not options["watch"]:
                    raise
                self.stderr.write("Notification database unavailable; retrying.")
            if not options["watch"]:
                break
            close_old_connections()
            time.sleep(5)
