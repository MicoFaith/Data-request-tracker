import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from desk.importer import import_episodes
from desk.models import User, DemoSeedState


class Command(BaseCommand):
    help = "Create supplied demo users, then import supplied episodes; safe to rerun."

    def add_arguments(self, parser):
        parser.add_argument("--skip-episodes", action="store_true")
        parser.add_argument(
            "--once",
            action="store_true",
            help="Skip if startup seeding already completed for this database.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            if options["once"] and DemoSeedState.objects.filter(pk="demo-v1").exists():
                self.stdout.write(
                    "Demo already initialized; keeping account changes and deletions."
                )
                return
            self.seed(options)
            if options["once"]:
                DemoSeedState.objects.get_or_create(pk="demo-v1")

    def seed(self, options):
        with transaction.atomic():
            for item in json.loads((settings.BASE_DIR / "seed/users.json").read_text()):
                user, created = User.objects.get_or_create(
                    username=item["email"],
                    defaults={
                        "email": item["email"],
                        "display_name": item["name"],
                        "role": item["role"],
                        "organisation": item.get("organisation", ""),
                    },
                )
                if created:
                    user.set_password(item["password"])
                    user.save(update_fields=["password"])
        if not options["skip_episodes"]:
            actor = User.objects.filter(
                is_active=True, role__in=["operator", "admin"]
            ).first()
            if actor:
                with (settings.BASE_DIR / "seed/episodes.csv").open(
                    encoding="utf-8-sig", newline=""
                ) as stream:
                    report = import_episodes(actor, stream)
                self.stdout.write(json.dumps(report))
            else:
                self.stdout.write(
                    "No active operator/admin; skipped seed episode import."
                )
        self.stdout.write("Seed users ready; existing accounts were not overwritten.")
