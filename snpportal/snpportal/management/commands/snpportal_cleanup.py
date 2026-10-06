"""python manage.py snpportal_cleanup: delete expired results (for cron); the portal also does this on page views."""
from django.core.management.base import BaseCommand

from snpportal import jobs


class Command(BaseCommand):
    help = "Delete result folders older than SNPPORTAL_KEEP_HOURS (default 24) and stray upload files."

    def handle(self, *args, **options):
        self.stdout.write(f"Removed {jobs.cleanup()} expired result(s).")
