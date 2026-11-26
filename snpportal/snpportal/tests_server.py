"""The portal on the salmobase server (G, 2026-11-25): one setting names the server's datafiles folder, and the
published releases, the genome and the track files are read where they are. The species bar shows the releases this
version names, also when a newer one has been published; nothing is written in the published folder."""
import io
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpdata

from . import jobs, serve

DATA = Path(__file__).resolve().parents[2] / "snpdata"
FIXTURE = DATA / "tests" / "fixture"
TROUT = FIXTURE / "rainbow_trout"
GENOME = "genomes/AtlanticSalmon/Ssal_v3.1/sequence_Ensembl/Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz"


def listing(folder):
    return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(folder).rglob("*") if p.is_file())


@skipUnless(TROUT.exists(), "needs snpdata/ next to snpportal/")
class ServerTest(SimpleTestCase):
    def test_published_data_is_read_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            served = Path(tmp).resolve() / "datafiles"
            releases = serve.published(served)
            self.assertEqual(releases, served / "datasets" / "salmo-snp" / "releases")  # where salmobase publishes them
            self.assertIsNone(serve.published(None))
            salmon = snpdata.build(DATA / "layers.yaml", FIXTURE, releases / "2026-01-01")
            trout = snpdata.build(DATA / "rainbow_trout" / "layers.yaml", TROUT, releases / "trout-2026-01-01")
            for release in (salmon, trout):  # as published: the genome's path on the build machine is not on this one
                m = json.loads((release / "manifest.json").read_text())
                m["genome"]["path"] = "/the/build/machine/" + m["genome"]["file"]
                (release / "manifest.json").write_text(json.dumps(m))
            newer = shutil.copytree(trout, releases / "trout-2026-02-02")  # published since: this version does not name it
            (newer / "manifest.json").write_text(json.dumps({**m, "version": "trout-2026-02-02", "created": "2099-01-01"}))
            (served / GENOME).parent.mkdir(parents=True)
            for ext in ("", ".fai", ".gzi"):  # the genome where the manifest's address says it is
                shutil.copy(FIXTURE / (Path(GENOME).name + ext), str(served / GENOME) + ext)
            before = listing(served)
            named = {"atlantic_salmon": "2026-01-01", "rainbow_trout": "trout-2026-01-01"}
            logging.disable(logging.WARNING)
            try:
                with mock.patch.dict(os.environ, {"SNPSCORE_SALMOBASE": str(served)}), mock.patch.object(serve, "RELEASE", "2026-01-01"), \
                        mock.patch.dict(serve.RELEASES, named), \
                        override_settings(SNPSCORE_RELEASE=str(releases / "2026-01-01"), SNPPORTAL_RELEASES_DIR=str(releases),
                                          SNPPORTAL_RESULTS_DIR=str(Path(tmp) / "data" / "results"), SNPPORTAL_WORKERS=0, SNPPORTAL_LOCAL=False):
                    self.assertEqual({k: f.name for k, f in jobs.species_releases().items()}, named)
                    h = self.client.get(reverse("snpportal:health") + "?tracks=1").json()
                    self.assertEqual((h["status"], h["genome"], h["species"], h["pool_fits"]), ("ok", "local", named, False))
                    self.assertRegex(h["tracks"]["read from the disk"], r"^0 of \d+$")  # this folder holds no track file
                    said = io.StringIO()  # what the service says before it starts; the published folder is read only
                    with mock.patch("snpportal.management.commands.snpportal_prepare.os.access", return_value=False):
                        call_command("snpportal_prepare", stdout=said)
                    self.assertIn("release 2026-01-01 (Atlantic salmon): genome on the disk", said.getvalue())
                    self.assertIn("release trout-2026-01-01 (Rainbow trout): genome read from its address", said.getvalue())
                    self.assertEqual(said.getvalue().count("PUBLIC POOL MISSING"), 2)
                    self.assertNotIn("trout-2026-02-02", said.getvalue())
                    url = self.client.post(reverse("snpportal:upload"), {"example": "known_loci"}).url.split("?")[0]
                    job = jobs.read_json(jobs.folder(url.rstrip("/").split("/")[-1]) / "job.json")
                    self.assertEqual((job["state"], job["release"]), ("done", "2026-01-01"))
                    self.assertEqual(self.client.get(url).status_code, 200)
                    with override_settings(SNPSCORE_RELEASE=str(releases / "2026-03-03")), \
                            self.assertRaisesRegex(CommandError, "no release at .*2026-03-03: this version expects release 2026-01-01"):
                        call_command("snpportal_prepare", stdout=io.StringIO())
                    self.beside_another_site(url)
            finally:
                logging.disable(logging.NOTSET)
            self.assertEqual(listing(served), before)  # nothing was written where the data is published

    def beside_another_site(self, result):
        """At /snp/ beside salmobase's own Django on one host: the portal's cookies have names of their own and go to
        its own pages only, and a result's page is not indexed and not framed by other sites."""
        with override_settings(SNPPORTAL_COOKIE_PATH="/snp/", CSRF_COOKIE_PATH="/snp/"):
            page = self.client.get(reverse("snpportal:upload"))
            self.assertEqual(page.cookies["snpportal_csrftoken"]["path"], "/snp/")
            self.assertNotIn("csrftoken", page.cookies)  # the name salmobase's own forms would use
            switched = self.client.post(reverse("snpportal:species"), {"species": "rainbow_trout"})
            self.assertEqual(switched.cookies["snp_species"]["path"], "/snp/")
            shown = self.client.get(result)
            self.assertEqual((shown["X-Robots-Tag"], shown["X-Frame-Options"], shown["X-Content-Type-Options"]),
                             ("noindex", "SAMEORIGIN", "nosniff"))
