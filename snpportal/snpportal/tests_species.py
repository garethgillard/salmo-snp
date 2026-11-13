"""Two species side by side (Atlantic salmon and rainbow trout): the species bar picks the release new work uses, by a
cookie, also on a server; a job's pages keep the job's own release; a trout page says trout things."""
import logging
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpdata

from . import jobs

DATA = Path(__file__).resolve().parents[2] / "snpdata"
TROUT = DATA / "tests" / "fixture_trout"


@skipUnless(TROUT.exists(), "needs snpdata/ next to snpportal/")
class SpeciesTest(SimpleTestCase):
    def test_species_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snpdata.build(DATA / "layers.yaml", DATA / "tests" / "fixture", tmp / "releases" / "salmon-test")
            snpdata.build(DATA / "rainbow_trout" / "layers.yaml", TROUT, tmp / "releases" / "trout-test")
            with override_settings(SNPSCORE_RELEASE=str(tmp / "releases" / "salmon-test"), SNPPORTAL_RELEASES_DIR=str(tmp / "releases"),
                                   SNPPORTAL_RESULTS_DIR=str(tmp / "data" / "results"), SNPPORTAL_WORKERS=0, SNPPORTAL_LOCAL=False):
                logging.disable(logging.WARNING)
                try:
                    self.flow()
                finally:
                    logging.disable(logging.NOTSET)

    def page(self, name="snpportal:upload", **kwargs):
        return self.client.get(reverse(name, **kwargs)).content.decode()

    def flow(self):
        home = self.page()
        self.assertIn('value="rainbow_trout"', home)  # the bar offers both; salmon is the default
        self.assertIn('value="atlantic_salmon" aria-pressed="true"', home)
        self.assertIn("Ssal_v3.1", home)
        self.assertIn("Known loci", home)
        self.assertEqual(self.client.post(reverse("snpportal:species"), {"species": "rainbow_trout"}).url, reverse("snpportal:upload"))
        home = self.page()
        self.assertIn('value="rainbow_trout" aria-pressed="true"', home)
        self.assertIn("Upload rainbow trout SNPs (positions on USDA_OmykA_1.1", home)
        self.assertRegex(home, r"1\d AQUA-FAANG tissues and stages")  # 17 genome-wide; the fixture's regions have fewer
        self.assertNotIn("21 AQUA-FAANG", home)
        self.assertNotIn("Ssal_v3.1", home)
        self.assertNotIn("Known loci", home)  # this release has no catalogue
        self.assertIn(">Atlantic salmon</button>", home)  # the other species keeps its name
        self.assertIn("28:12020000-12210000", home)  # the Locus browser opens at the species' example
        url = self.client.post(reverse("snpportal:upload"), {"paste": "omy28 12029722 T C\nY 6002000 G A\n"}).url.split("?")[0]
        key = url.rstrip("/").split("/")[-1]
        self.assertEqual(jobs.read_json(jobs.folder(key) / "job.json")["release"], "trout-test")
        self.assertEqual(jobs.read_json(jobs.folder(key) / "summary.json")["n_rows"], 2)
        self.client.post(reverse("snpportal:species"), {"species": "atlantic_salmon"})
        self.assertIn("Ssal_v3.1", self.page())
        result = self.client.get(url).content.decode()  # the trout job stays a trout page
        self.assertIn("USDA_OmykA_1.1", result)
        self.assertIn('value="rainbow_trout" aria-pressed="true"', result)
        self.client.post(reverse("snpportal:species"), {"species": "no_such_fish"})  # ignored
        self.assertIn("Ssal_v3.1", self.page())
        data = self.client.get(reverse("snpportal:about_data"))
        self.assertContains(data, "504 public fish")
        self.client.post(reverse("snpportal:species"), {"species": "rainbow_trout"})
        data = self.page("snpportal:about_data")
        self.assertIn("AQUA-FAANG rainbow trout BodyMap", data)
        self.assertIn("PRJEB109732", data)
        self.assertNotIn("504", data)
        self.assertEqual(self.client.get(reverse("snpportal:releases")).status_code, 404)  # the Releases page is a local install's
