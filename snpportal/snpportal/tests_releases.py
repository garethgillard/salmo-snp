"""Several releases side by side on a local install (ROADMAP I17): the Releases page switches the release new work
uses; a job's pages keep reading the job's own release; a Design panel takes SNPs of one release only."""
import logging
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpdata

from . import jobs

DATA = Path(__file__).resolve().parents[2] / "snpdata"
FIXTURE = DATA / "tests" / "fixture"


@skipUnless(FIXTURE.exists(), "needs snpdata/ next to snpportal/")
class ReleasesTest(SimpleTestCase):
    def test_switch_and_keep_each_jobs_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name in ("rel-a", "rel-b"):  # the same data, two release versions (a version is its folder's name)
                snpdata.build(DATA / "layers.yaml", FIXTURE, tmp / "releases" / name)
            with override_settings(SNPSCORE_RELEASE=str(tmp / "releases" / "rel-a"), SNPPORTAL_RELEASES_DIR=str(tmp / "releases"),
                                   SNPPORTAL_RESULTS_DIR=str(tmp / "data" / "results"), SNPPORTAL_WORKERS=0, SNPPORTAL_LOCAL=True):
                logging.disable(logging.WARNING)
                try:
                    self.flow()
                finally:
                    logging.disable(logging.NOTSET)

    def score(self):
        url = self.client.post(reverse("snpportal:upload"), {"paste": "25 28996360 C T\n25 28998410 C G\n"}).url.split("?")[0]
        return url, url.rstrip("/").split("/")[-1]

    def flow(self):
        a_url, a = self.score()
        self.assertIn("Release rel-a", self.client.get(a_url).content.decode())
        page = self.client.get(reverse("snpportal:releases")).content.decode()
        self.assertIn("rel-b", page)
        self.assertIn("<strong>in use</strong>", page)
        self.client.post(reverse("snpportal:releases"), {"version": "rel-b"})
        score = self.client.get(reverse("snpportal:upload")).content.decode()
        self.assertIn("Release rel-b", score)  # the badge, a link to the Releases page
        self.assertIn(", release rel-b)", score)  # the Score page names the release (and assembly) it scores with
        b_url, b = self.score()
        self.assertEqual(jobs.read_json(jobs.folder(b) / "job.json")["release"], "rel-b")
        self.assertEqual(jobs.read_json(jobs.folder(a) / "job.json")["release"], "rel-a")
        self.assertIn("Release rel-a", self.client.get(a_url).content.decode())  # an older job keeps its own release
        self.assertIn("Release rel-b", self.client.get(b_url).content.decode())
        self.client.post(reverse("snpportal:panel_add", args=[a]))
        self.assertIn("panel_error=release", self.client.post(reverse("snpportal:panel_add", args=[b])).url)
        self.assertIn("Release rel-a", self.client.get(reverse("snpportal:design_panel")).content.decode())  # the panel's own
        self.client.post(reverse("snpportal:releases"), {"version": ""})  # back to the default
        self.assertIn("Release rel-a", self.client.get(reverse("snpportal:upload")).content.decode())
        with override_settings(SNPPORTAL_LOCAL=False):
            self.assertEqual(self.client.get(reverse("snpportal:releases")).status_code, 404)
