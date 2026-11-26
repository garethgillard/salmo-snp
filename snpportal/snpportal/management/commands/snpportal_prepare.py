"""python manage.py snpportal_prepare: what a server checks before the portal starts (deploy/server.sh runs it). For
each species' release that new work is scored against: that it is there, where its genome and its track files are
read from, and its public pool, which is built here when the release's folder may be written to and is reported when
it does not fit this version's weights and the folder is read only (a published folder: its pools are built on Orion
and published with the release). Fails when the default release is missing."""
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from snpportal import jobs, serve
from snpscore import bbi
from snpscore.annotate import genome_location
from snpscore.pool import build_pool, stale


class Command(BaseCommand):
    help = "Check each species' release, its genome, tracks and public pool before the portal starts"

    def handle(self, *args, **options):
        default = Path(settings.SNPSCORE_RELEASE)
        if not (default / "manifest.json").is_file():
            raise CommandError(f"no release at {default}: this version expects release {serve.RELEASE} (is it published, "
                               "and is the folder it is in set and readable? SNPSCORE_SALMOBASE or SNPSCORE_RELEASE)")
        for folder in jobs.species_releases().values():
            m = jobs.manifest(folder)
            where = genome_location(m) or ""
            said = [f"genome {'not named' if not where else 'read from its address' if '://' in where else 'on the disk'}"]
            try:
                from snpportal.lib import tracks
                registry = tracks.load_tracks(folder)
                urls = [t["url"] for k in tracks.KEYS for t in registry.get(k, [])]
                said.append(f"{sum(bbi.local(u) != u for u in urls)} of {len(urls)} track files on the disk")
            except (OSError, ValueError):
                said.append("no track registry")
            if not stale(folder):
                said.append("public pool fits")
            elif os.access(folder, os.W_OK) and os.environ.get("SNPPORTAL_POOL_BUILD") != "0":  # 0: never here (NREC)
                self.stdout.write(f"release {m.get('version')}: building its public pool (a minute or two)")
                build_pool(folder, memory_limit=os.environ.get("SNPPORTAL_POOL_MEMORY", "4GB"))
                said.append("public pool built")
            else:
                said.append("PUBLIC POOL MISSING OR BUILT FOR OTHER WEIGHTS, and none is built here (a read-only folder, or "
                            "SNPPORTAL_POOL_BUILD=0): the Overview leaves out the public comparison until a pool that fits "
                            "is published or sent (docs/SALMOBASE.md)")
            self.stdout.write(f"release {m.get('version')} ({jobs.species(folder)['name']}): " + "; ".join(said))
