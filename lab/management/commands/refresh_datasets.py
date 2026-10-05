"""Bounded historical refresh command for a once-daily server timer."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.providers import last_completed_day
from core.parser import ProblemError
from lab.fetching import next_batch, refresh_record, pending
from lab.models import FetchRequest


class Command(BaseCommand):
    help = "Refresh the chosen owner’s watched historical universes; retain immutable snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        parser.add_argument("--max-batches", type=int, default=20)

    def handle(self, *args, **options):
        owner = (
            get_user_model()
            .objects.filter(username=options["owner"], is_staff=True)
            .first()
        )
        if owner is None:
            raise CommandError(
                "Choose an existing staff/superuser owner, not the shared guest."
            )
        if not 1 <= options["max_batches"] <= 1000:
            raise CommandError("max-batches must be between 1 and 1000.")
        count = 0
        for record in FetchRequest.objects.filter(owner=owner, refresh_daily=True):
            if count >= options["max_batches"]:
                break
            if (
                record.completed_at
                and record.completed_at.date() == timezone.now().date()
                and record.end >= last_completed_day()
            ):
                continue
            try:
                if record.dataset or record.errors:
                    refresh_record(record)
                while pending(record) and count < options["max_batches"]:
                    next_batch(record)
                    count += 1
                    record.refresh_from_db()
                self.stdout.write(
                    f"{record.name}: {len(record.series)}/{len(record.symbols)} symbols; {len(record.errors)} errors."
                )
            except ProblemError as error:
                self.stderr.write(f"{record.name}: {error}")
        self.stdout.write(
            f"Completed {count} historical batches. No trading endpoints used."
        )
