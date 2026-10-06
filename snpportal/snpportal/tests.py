"""End-to-end: build a release from salmo-snpscore's fixture, upload its VCF, sort and page the results, download them."""
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpscore

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"


@skipUnless((SNPSCORE / "tests" / "fixture").exists(), "needs the salmo-snpscore repo next to this one")
class PortalTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        release = snpscore.build(SNPSCORE / "layers.yaml", SNPSCORE / "tests" / "fixture", Path(cls.tmp.name) / "test")
        cls.override = override_settings(SNPSCORE_RELEASE=str(release), SNPPORTAL_RESULTS_DIR=cls.tmp.name)
        cls.override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.override.disable()
        cls.tmp.cleanup()
        super().tearDownClass()

    def test_upload_sort_page_download(self):
        with open(SNPSCORE / "tests" / "fixture" / "snps.vcf", "rb") as f:
            response = self.client.post(reverse("snpportal:upload"), {"snps": f})
        self.assertEqual(response.status_code, 302)

        page = self.client.get(response.url + "?sort=pos&desc=1&page=2")
        self.assertContains(page, "Page 2 of 23")
        self.assertContains(page, "chromatin: ")

        download = self.client.get(response.url + "download/")
        self.assertIn(b"chromatin_Brain_Immature_Female", b"".join(download.streaming_content))

    def test_rejects_unknown_file_type(self):
        with open(SNPSCORE / "layers.yaml", "rb") as f:
            response = self.client.post(reverse("snpportal:upload"), {"snps": f})
        self.assertContains(response, "Upload a .vcf")
